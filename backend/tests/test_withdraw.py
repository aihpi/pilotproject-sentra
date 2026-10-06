"""Taking a document out of the corpus without destroying it.

Withdrawal is one of the two operations `SOURCE_MANAGEMENT_NOTES.md`
distinguishes. The points go, so the document stops being searchable and
citable. The registry row and the PDF stay, so the decision is reversible and
the system can still answer whether a document was in the corpus when a past
answer was generated.

The property most worth protecting is the one that is easy to miss: **a
withdrawn document stays withdrawn across an ingestion run.** The skip filter
asks Qdrant what is already indexed, and a document whose points have just been
removed looks like one that has never been seen, so without the registry check
the next run would parse and re-embed it.
"""

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sentra.db import Base
from sentra.documents import models, registry


@pytest.fixture
def registry_session():
    """An in-memory registry, as test_document_registry.py builds one."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _add(session, name: str, *, status: str = models.INDEXED) -> models.Document:
    document = models.Document(
        id=uuid4(),
        content_hash=uuid4().hex,
        storage_key=f"store/{name}",
        original_name=name,
        status=status,
        source=models.FOLDER_IMPORT,
    )
    document.files.append(models.DocumentFile(original_name=name, storage_key=f"store/{name}"))
    session.add(document)
    session.flush()
    return document


class TestWithdraw:
    def test_sets_the_status_and_returns_the_id(self, registry_session):
        document = _add(registry_session, "WD 1-008-25.pdf")

        returned = registry.withdraw(registry_session, "WD 1-008-25.pdf")

        assert returned == document.id
        assert document.status == models.WITHDRAWN

    def test_keeps_the_row(self, registry_session):
        """Withdrawal is reversible, and past answers cited this document."""
        document = _add(registry_session, "a.pdf")

        registry.withdraw(registry_session, "a.pdf")

        assert registry_session.get(models.Document, document.id) is not None

    def test_an_unknown_name_is_not_an_error(self, registry_session):
        """The caller asked for it gone, and it is not here.

        Reported rather than raised, because the interesting case is the
        corpus and the registry disagreeing, which drift already surfaces.
        """
        assert registry.withdraw(registry_session, "never-existed.pdf") is None

    def test_finds_a_document_by_any_of_its_names(self, registry_session):
        """A document filed twice is indexed under both names."""
        document = _add(registry_session, "primary.pdf")
        document.files.append(
            models.DocumentFile(original_name="also-known-as.pdf", storage_key="store/aka.pdf")
        )
        registry_session.flush()

        assert registry.withdraw(registry_session, "also-known-as.pdf") == document.id


class TestWithdrawnFilenames:
    def test_lists_every_name_of_every_withdrawn_document(self, registry_session):
        gone = _add(registry_session, "gone.pdf", status=models.WITHDRAWN)
        gone.files.append(
            models.DocumentFile(original_name="gone-too.pdf", storage_key="store/gone-too.pdf")
        )
        _add(registry_session, "kept.pdf")
        registry_session.flush()

        assert registry.withdrawn_filenames(registry_session) == {"gone.pdf", "gone-too.pdf"}

    def test_is_empty_when_nothing_is_withdrawn(self, registry_session):
        _add(registry_session, "kept.pdf")

        assert registry.withdrawn_filenames(registry_session) == set()


class TestDriftIgnoresWithdrawn:
    def test_a_withdrawn_document_is_not_an_orphan(self, registry_session):
        """It has no points on purpose, which is not the same as missing."""
        _add(registry_session, "gone.pdf", status=models.WITHDRAWN)

        found = registry.drift(registry_session, indexed_names=[])

        assert found.row_without_chunks == []


class TestIngestionSkipsWithdrawn:
    """The property that makes withdrawal mean anything."""

    @pytest.mark.parametrize("force", [False, True])
    def test_a_withdrawn_file_is_skipped_however_the_run_started(
        self, force, registry_session, tmp_path, monkeypatch
    ):
        """Force means re-embed what is in the corpus, not resurrect what left."""
        from sentra.services import ingest

        (tmp_path / "gone.pdf").write_bytes(b"%PDF")
        (tmp_path / "kept.pdf").write_bytes(b"%PDF")
        _add(registry_session, "gone.pdf", status=models.WITHDRAWN)
        registry_session.commit()

        # parse_pdfs takes the directory and the pre-filtered paths, so what
        # it is handed is exactly the skip decision under test.
        # Ingestion opens its own session against the configured registry.
        # Pointed at the in-memory one, or the skip would be read from
        # whatever database happens to be running.
        @contextmanager
        def _session():
            yield registry_session

        monkeypatch.setattr(ingest, "session_scope", _session)

        parsed: list[str] = []

        def _capture(_dir, pdf_paths):
            parsed.extend(path.name for path in pdf_paths)
            return []

        monkeypatch.setattr(ingest, "parse_pdfs", _capture)

        ingest._run_ingestion_inner(_StoreStub(), _EmbedderStub(), _settings(tmp_path), force=force)

        assert "gone.pdf" not in parsed
        assert "kept.pdf" in parsed


class TestRegistryUnreachable:
    def test_a_skip_only_run_still_works(self, tmp_path, monkeypatch):
        """A dependency being down must not fail a run that writes nothing.

        The offline test tier has no Postgres, and neither did CI, which is
        how this was caught: an unconditional registry query at the top of
        ingestion turned "everything is already indexed" into a failed run.

        Anything that would actually be written fails per file at
        register_file moments later, which is loud and specific, so there is
        nothing to gain by failing earlier and less precisely.
        """
        from sentra.db import RegistryDatabaseUnavailable
        from sentra.services import ingest

        (tmp_path / "a.pdf").write_bytes(b"%PDF")

        def _unreachable():
            raise RegistryDatabaseUnavailable("connection refused")

        monkeypatch.setattr(ingest, "session_scope", _unreachable)

        parsed: list[str] = []

        def _capture(_dir, pdf_paths):
            parsed.extend(path.name for path in pdf_paths)
            return []

        monkeypatch.setattr(ingest, "parse_pdfs", _capture)

        ingest._run_ingestion_inner(_StoreStub(), _EmbedderStub(), _settings(tmp_path), force=False)

        assert parsed == ["a.pdf"]


class _StoreStub:
    def get_indexed_source_files(self) -> set[str]:
        return set()

    def ensure_collection(self) -> None: ...

    def ensure_doc_collection(self) -> None: ...


class _EmbedderStub: ...


def _settings(tmp_path: Path):
    from sentra.config import Settings

    return Settings(
        ai_hub_base_url="http://hub.invalid/v1",
        ai_hub_api_key="nicht-echt",
        documents_dir=str(tmp_path),
    )
