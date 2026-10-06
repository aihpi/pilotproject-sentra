"""Putting a file on the documents volume.

The filename is the whole risk here. It arrives in a multipart header chosen
by whoever is uploading, and it decides where bytes land in a directory that
ingestion walks and that `GET /documents/{filename}` serves out of by name.

Most of these tests are about refusing things, and one property is worth
stating outright because it is a deliberate choice rather than an oversight:
**a path-shaped name is refused, not repaired.** `Path("../../x").name` is
`"x"`, so sanitising by truncation would quietly write somewhere other than
what was asked for, and succeed. Silently doing something different from what
you were told is the failure worth avoiding, so anything path-shaped is an
error the uploader sees.
"""

import secrets

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentra.api.identity import hash_password
from sentra.api.routes import router
from sentra.config import Settings, get_settings
from sentra.services import uploads
from sentra.services.uploads import RejectedUpload


class TestSafeName:
    @pytest.mark.parametrize(
        "name",
        [
            "../../etc/passwd",
            "../WD 1-008-25.pdf",
            "subdir/WD 1-008-25.pdf",
            "..\\..\\windows\\system32\\x.pdf",
            "a\\b.pdf",
            "/absolute/WD.pdf",
        ],
    )
    def test_a_path_is_refused_rather_than_truncated(self, name):
        """The failure this is here to prevent.

        Path(name).name would turn every one of these into something
        harmless-looking and write it, reporting success for an act nobody
        asked for.
        """
        with pytest.raises(RejectedUpload):
            uploads.safe_name(name)

    @pytest.mark.parametrize("name", ["", "   ", None])
    def test_no_name_is_refused(self, name):
        with pytest.raises(RejectedUpload):
            uploads.safe_name(name)

    @pytest.mark.parametrize("name", [".", "..", ".hidden.pdf"])
    def test_dot_names_are_refused(self, name):
        with pytest.raises(RejectedUpload):
            uploads.safe_name(name)

    def test_a_null_byte_is_refused(self):
        with pytest.raises(RejectedUpload):
            uploads.safe_name("WD\x00.pdf")

    def test_control_characters_are_refused(self):
        """It ends up in logs, in the registry, and in a response header."""
        with pytest.raises(RejectedUpload):
            uploads.safe_name("WD\n1-008.pdf")

    def test_an_over_long_name_is_refused(self):
        with pytest.raises(RejectedUpload):
            uploads.safe_name("a" * 300 + ".pdf")

    @pytest.mark.parametrize("name", ["notes.txt", "archive.zip", "script.sh", "WD.pdf.exe"])
    def test_an_unlisted_suffix_is_refused(self, name):
        with pytest.raises(RejectedUpload):
            uploads.safe_name(name)

    @pytest.mark.parametrize(
        "name",
        [
            "WD 1-008-25.pdf",
            "WD 4-003-25; WD 3-003-25.pdf",
            "EU 6-012-25.PDF",
            "WD 6-004-25_Abstract.docx",
            "Gutachten (Fassung 2).pdf",
        ],
    )
    def test_the_names_the_corpus_actually_uses_are_accepted(self, name):
        """Real filenames from the corpus: spaces, semicolons, brackets, case."""
        assert uploads.safe_name(name) == name


class TestStore:
    def test_writes_the_file(self, tmp_path):
        name, size = uploads.store(_bytes(b"%PDF-1.4 hello"), "WD 1-008-25.pdf", tmp_path)

        assert name == "WD 1-008-25.pdf"
        assert size == 14
        assert (tmp_path / name).read_bytes() == b"%PDF-1.4 hello"

    def test_creates_the_directory_if_it_is_not_there(self, tmp_path):
        target = tmp_path / "Ausarbeitungen"

        uploads.store(_bytes(b"x"), "a.pdf", target)

        assert (target / "a.pdf").exists()

    def test_refuses_to_overwrite(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"original")

        with pytest.raises(RejectedUpload, match="bereits vorhanden"):
            uploads.store(_bytes(b"replacement"), "a.pdf", tmp_path)

        assert (tmp_path / "a.pdf").read_bytes() == b"original"

    def test_refuses_an_empty_file(self, tmp_path):
        with pytest.raises(RejectedUpload, match="leer"):
            uploads.store(_bytes(b""), "a.pdf", tmp_path)

        assert list(tmp_path.iterdir()) == []

    def test_refuses_a_file_over_the_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(uploads, "MAX_FILE_BYTES", 1024)

        with pytest.raises(RejectedUpload, match="größer"):
            uploads.store(_bytes(b"x" * 2048), "a.pdf", tmp_path)

    def test_leaves_nothing_behind_when_it_refuses(self, tmp_path, monkeypatch):
        """A rejected upload must not leave a partial file.

        Ingestion globs this directory. Debris that a later glob picks up is
        worse than the failure that produced it.
        """
        monkeypatch.setattr(uploads, "MAX_FILE_BYTES", 1024)

        with pytest.raises(RejectedUpload):
            uploads.store(_bytes(b"x" * 2048), "a.pdf", tmp_path)

        assert list(tmp_path.iterdir()) == []

    def test_the_destination_never_exists_half_written(self, tmp_path):
        """Written under a temporary name and renamed.

        Asserted through the temporary name's suffix rather than by racing the
        write: a `.part` file is outside the `*.pdf` glob, which is what makes
        the window safe.
        """
        seen = []

        class Watching:
            def __init__(self):
                self._chunks = [b"a" * 1024, b"b" * 1024]

            def read(self, _size):
                seen.extend(p.name for p in tmp_path.iterdir())
                return self._chunks.pop(0) if self._chunks else b""

        uploads.store(Watching(), "a.pdf", tmp_path)

        assert (tmp_path / "a.pdf").exists()
        assert not any(name == "a.pdf" for name in seen)
        assert all(name.endswith(".part") for name in seen if name)


class TestListing:
    def test_a_missing_directory_is_empty_rather_than_an_error(self, tmp_path):
        """It means nothing was ever put there, which is a real state."""
        assert uploads.listing(tmp_path / "nope") == []

    def test_reports_name_size_and_whether_it_is_indexable(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"12345")
        (tmp_path / "b.docx").write_bytes(b"123")

        by_name = {f[0]: f for f in uploads.listing(tmp_path)}

        assert by_name["a.pdf"][1] == 5
        assert by_name["a.pdf"][3] is True
        # Read by the registry scan, never indexed: ingest.py globs *.pdf.
        assert by_name["b.docx"][3] is False

    def test_skips_uploads_still_in_flight(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"x")
        (tmp_path / ".upload-abc.part").write_bytes(b"x")

        assert [f[0] for f in uploads.listing(tmp_path)] == ["a.pdf"]

    def test_skips_files_nothing_would_read(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"x")
        (tmp_path / "notes.txt").write_bytes(b"x")

        assert [f[0] for f in uploads.listing(tmp_path)] == ["a.pdf"]


class TestEndpoints:
    def test_uploads_and_then_lists(self, client, documents_dir):
        response = client.post(
            "/api/documents", files=[("files", ("WD 1-008-25.pdf", b"%PDF-1.4", "application/pdf"))]
        )

        assert response.status_code == 200
        assert response.json()["accepted"] == 1
        assert (documents_dir / "WD 1-008-25.pdf").exists()

        listed = client.get("/api/documents/files").json()
        assert [f["name"] for f in listed] == ["WD 1-008-25.pdf"]
        assert listed[0]["indexable"] is True

    def test_one_bad_name_does_not_discard_the_good_ones(self, client, documents_dir):
        """Dragging in a folder with one unreadable name is the ordinary case."""
        response = client.post(
            "/api/documents",
            files=[
                ("files", ("good.pdf", b"%PDF", "application/pdf")),
                ("files", ("../escape.pdf", b"%PDF", "application/pdf")),
                ("files", ("notes.txt", b"hi", "text/plain")),
            ],
        )

        body = response.json()
        assert body["accepted"] == 1
        assert body["rejected"] == 2
        assert (documents_dir / "good.pdf").exists()
        assert not (documents_dir.parent / "escape.pdf").exists()

        rejected = {f["name"]: f["reason"] for f in body["files"] if not f["accepted"]}
        assert "Pfad" in rejected["../escape.pdf"]
        assert ".pdf" in rejected["notes.txt"]

    def test_a_reader_cannot_upload(self, client_with_login):
        """The tab being hidden is not what stops this; require_role is."""
        response = client_with_login.post(
            "/api/documents", files=[("files", ("a.pdf", b"%PDF", "application/pdf"))]
        )

        assert response.status_code == 401

    def test_anybody_may_list_the_volume(self, client_with_login):
        """Reading is not the guarded half.

        The corpus is published material and GET /documents beside it says
        more, so a guard here would protect filenames whose full metadata is
        already open. Noticing a document is missing is also exactly what the
        people using SENTRA do first.
        """
        assert client_with_login.get("/api/documents/files").status_code == 200


def _bytes(payload: bytes):
    import io

    return io.BytesIO(payload)


def _settings(tmp_path, **over) -> Settings:
    base = {
        "ai_hub_base_url": "http://hub.invalid/v1",
        "ai_hub_api_key": "nicht-echt",
        "documents_dir": str(tmp_path),
    }
    base.update(over)
    return Settings(**base)


@pytest.fixture
def documents_dir(tmp_path):
    target = tmp_path / "Ausarbeitungen"
    target.mkdir()
    return target


@pytest.fixture
def client(documents_dir):
    """Nothing configured to check against, so require_role is open.

    That is the deployment this pilot has had all along, and the upload path
    has to work there as well as behind a login.
    """
    app = FastAPI()
    # The router carries its own /api prefix.
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: _settings(documents_dir)
    return TestClient(app)


@pytest.fixture
def client_with_login(documents_dir):
    """A login configured and nobody signed in: require_role refuses."""
    password = secrets.token_urlsafe(16)
    settings = _settings(
        documents_dir,
        sentra_users=f"chef:admin:{hash_password(password)}",
        session_secret=secrets.token_urlsafe(32),
    )
    app = FastAPI()
    # The router carries its own /api prefix.
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)
