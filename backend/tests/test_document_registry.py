"""The registry, built from a directory and compared against the index.

Offline, against SQLite in memory. Nothing here needs Postgres, Qdrant or
Docling: the scan hashes files and reads filenames, which is the whole reason
it can be run repeatedly against a live deployment.

What it is really testing is that the registry can describe this corpus as it
actually is — several Aktenzeichen on one document, the same bytes under two
names, metadata the index holds that cannot be true — rather than as the
ingestion path assumed it would be.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sentra.db import Base
from sentra.documents import registry
from sentra.documents.models import NEEDS_REVIEW, PENDING, Document, DocumentFile


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _pdf(root, name, content=b"%PDF-1.4 irgendein Inhalt"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class TestWalkingTheCorpus:
    def test_a_file_becomes_a_row(self, session, tmp_path):
        _pdf(tmp_path, "WD 9-100-21.pdf")

        report = registry.scan(session, tmp_path)

        assert report.scanned == 1
        assert report.created == 1
        document = session.execute(select(Document)).scalar_one()
        assert document.original_name == "WD 9-100-21.pdf"
        assert document.status == PENDING

    def test_subdirectories_are_reached(self, session, tmp_path):
        """`glob("*.pdf")` is not recursive, which is how ~1950 files stayed
        invisible until the tree was flattened by hand. The flattening made the
        non-recursive glob correct by accident, and only until somebody adds a
        directory."""
        _pdf(tmp_path / "PE 6", "EU 6-012-25.pdf")
        _pdf(tmp_path, "WD 9-100-21.pdf", b"anders")

        report = registry.scan(session, tmp_path)

        assert report.scanned == 2

    def test_docx_are_recorded_but_not_treated_as_documents_to_index(self, session, tmp_path):
        """23 of these sit beside the PDFs and every glob in the codebase skips
        them, so nothing has ever reported that they exist. Recording them is
        not admitting them — whether they belong is still open."""
        _pdf(tmp_path, "WD 4-010-25 Abstract.docx", b"docx")

        report = registry.scan(session, tmp_path)

        assert report.by_suffix == {".docx": 1}

    def test_running_it_twice_writes_nothing(self, session, tmp_path):
        """Idempotent by content hash, which is what makes it safe on a
        schedule and what lets two runs be compared."""
        _pdf(tmp_path, "WD 9-100-21.pdf")
        registry.scan(session, tmp_path)

        second = registry.scan(session, tmp_path)

        assert second.created == 0
        assert second.unchanged == 1


class TestAktenzeichen:
    def test_a_joint_document_keeps_all_of_them(self):
        """The one-character difference from the ingestion path: finditer, not
        search. 59 documents in this corpus carry more than one, and the 64
        extra Aktenzeichen are dropped today."""
        found = registry.aktenzeichen_in("WD 1-019-24; WD 7-060-24.pdf")

        assert found == ["WD 1 - 3000 - 019/24", "WD 7 - 3000 - 060/24"]

    def test_three_on_one_document(self):
        found = registry.aktenzeichen_in("WD 2-040-24 WD 3-070-24 EU 6-026-24.pdf")

        assert len(found) == 3

    def test_the_first_is_the_primary_one(self, session, tmp_path):
        _pdf(tmp_path, "WD 1-019-24; WD 7-060-24.pdf")

        registry.scan(session, tmp_path)

        document = session.execute(select(Document)).scalar_one()
        assert document.primary_aktenzeichen == "WD 1 - 3000 - 019/24"
        assert len(document.aktenzeichen) == 2

    def test_a_name_with_none_is_a_human_problem(self, session, tmp_path):
        """92 files are named like this — `AB 01-23.pdf`, a different naming
        genre. A document nothing can cite is not something to guess at."""
        _pdf(tmp_path, "AB 01-23.pdf")

        report = registry.scan(session, tmp_path)

        document = session.execute(select(Document)).scalar_one()
        assert document.status == NEEDS_REVIEW
        assert "Kein Aktenzeichen" in document.review_reason
        assert report.unreadable_names == ["AB 01-23.pdf"]


class TestTheSameBytesTwice:
    def test_one_document_two_files(self, session, tmp_path):
        """Four documents in this corpus are filed twice, the same joint paper
        with its Aktenzeichen in a different order."""
        _pdf(tmp_path, "WD 3-017-23, WD 4-009-23.pdf", b"identisch")
        _pdf(tmp_path, "WD 4-009-23; WD 3-017-23 .pdf", b"identisch")

        report = registry.scan(session, tmp_path)

        assert report.created == 1
        assert len(report.duplicate_hashes) == 1
        document = session.execute(select(Document)).scalar_one()
        assert document.is_filed_twice
        assert len(document.files) == 2

    def test_the_second_name_is_not_reported_as_missing(self, session, tmp_path):
        """The reason `document_files` exists. Both names are in the index, so
        comparing against the primary name alone reported the other as
        orphaned — indistinguishable from the genuinely missing documents in
        #140, which need a completely different answer."""
        _pdf(tmp_path, "erste.pdf", b"identisch")
        _pdf(tmp_path, "zweite.pdf", b"identisch")
        registry.scan(session, tmp_path)

        found = registry.drift(session, ["erste.pdf", "zweite.pdf"])

        assert found.indexed_without_row == []
        assert found.is_clean


class TestWhatTheIndexClaims:
    def test_a_date_that_is_not_a_date_is_flagged(self, session, tmp_path):
        """From the live index: the extractor swallowed the Aktenzeichen line of
        a joint document. completion_date drives the date-range filter, so such
        a document falls out of every filtered search — silently, and only for
        the documents hardest to extract in the first place."""
        _pdf(tmp_path, "WD 9-081-21; WD 3-164-21.pdf")
        known = {
            "WD 9-081-21; WD 3-164-21.pdf": {
                "completion_date": "WD 3 - 3000 - 164/21 und WD 9 - 3000 - 081/21 20. September 2021"
            }
        }

        report = registry.scan(session, tmp_path, known=known)

        document = session.execute(select(Document)).scalar_one()
        assert document.status == NEEDS_REVIEW
        assert "completion_date" in document.review_reason
        assert report.bad_completion_date

    def test_a_real_date_is_not(self, session, tmp_path):
        _pdf(tmp_path, "WD 9-100-21.pdf")
        known = {"WD 9-100-21.pdf": {"completion_date": "2021-09-20", "title": "Pandemie"}}

        registry.scan(session, tmp_path, known=known)

        document = session.execute(select(Document)).scalar_one()
        assert document.status == PENDING
        assert document.title == "Pandemie"

    def test_the_index_never_overwrites_what_the_registry_has(self, session, tmp_path):
        """The registry is becoming the source of truth, so the dependency only
        points one way — and the human overrides layer has to be able to
        outrank this."""
        _pdf(tmp_path, "WD 9-100-21.pdf")
        registry.scan(session, tmp_path, known={"WD 9-100-21.pdf": {"title": "Erster Titel"}})

        registry.scan(session, tmp_path, known={"WD 9-100-21.pdf": {"title": "Zweiter Titel"}})

        document = session.execute(select(Document)).scalar_one()
        assert document.title == "Erster Titel"

    def test_the_scan_works_with_nothing_known(self, session, tmp_path):
        """A registry that could not be built without the thing it is meant to
        become the source of truth for would be the wrong way round."""
        _pdf(tmp_path, "WD 9-100-21.pdf")

        report = registry.scan(session, tmp_path, known={})

        assert report.created == 1


class TestDrift:
    def test_indexed_with_no_row_is_reported(self, session, tmp_path):
        """#140, as a query rather than the hand-run diff that found it."""
        _pdf(tmp_path, "WD 9-100-21.pdf")
        registry.scan(session, tmp_path)

        found = registry.drift(session, ["WD 9-100-21.pdf", "WD 10-013-23.pdf"])

        assert found.indexed_without_row == ["WD 10-013-23.pdf"]
        assert found.is_clean is False

    def test_a_row_with_no_chunks_is_reported_too(self, session, tmp_path):
        """The quieter direction: a document nobody can find, which is worse to
        discover late."""
        _pdf(tmp_path, "WD 9-100-21.pdf")
        registry.scan(session, tmp_path)

        found = registry.drift(session, [])

        assert found.row_without_chunks == ["WD 9-100-21.pdf"]

    def test_agreement_is_counted(self, session, tmp_path):
        _pdf(tmp_path, "WD 9-100-21.pdf")
        registry.scan(session, tmp_path)

        found = registry.drift(session, ["WD 9-100-21.pdf"])

        assert found.agreed == 1
        assert found.is_clean


class TestNothingIsTouchedButTheRegistry:
    def test_the_scan_reaches_neither_the_index_nor_the_parser(self):
        """The reason this task comes first: it observes and changes nothing,
        so it is safe against a live deployment and can be run now rather than
        after hours of Docling.

        Checked on what the module imports rather than on what it contains. A
        scan that grows a Qdrant client is a scan that can no longer be run
        while a round is in flight, and that is the property worth protecting —
        not the absence of a word.
        """
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(registry))
        imported = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }

        assert not any("qdrant" in name or "rag" in name for name in imported), imported
        assert not any("docling" in name or "parser" in name for name in imported), imported


class TestFilesOnDisk:
    def test_every_document_has_at_least_one_file_row(self, session, tmp_path):
        _pdf(tmp_path, "WD 9-100-21.pdf")
        _pdf(tmp_path, "WD 3-029-23.pdf", b"anders")

        registry.scan(session, tmp_path)

        files = session.execute(select(DocumentFile)).scalars().all()
        assert len(files) == 2

    def test_the_storage_key_is_relative_to_the_root(self, session, tmp_path):
        """Opaque on purpose: a content-addressed store or S3 later is a change
        in one place."""
        _pdf(tmp_path / "PE 6", "EU 6-012-25.pdf")

        registry.scan(session, tmp_path)

        document = session.execute(select(Document)).scalar_one()
        assert document.storage_key == "PE 6/EU 6-012-25.pdf"
