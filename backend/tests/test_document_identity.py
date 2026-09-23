"""A document is its contents, not its filename.

This is what #140 is. Seventeen documents are indexed, searchable and citable
with no file behind them, and the source card 404s — the original seventeen,
indexed under names that the flattening of `data/` later changed. A point keyed
on a filename cannot survive a rename: the old points stay, the new ones are
written beside them, and nothing connects the two.

Keyed on content, a rename is a rename.

Against SQLite in memory for the registry half, and a fake collection for the
Qdrant half: what is under test is which id a point gets and what is deleted
before it is written, neither of which needs a vector database to answer.
"""

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sentra.db import Base
from sentra.documents import registry
from sentra.documents.models import Document
from sentra.domain import Chunk, DocumentMetadata


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _pdf(root: Path, name: str, content: bytes = b"%PDF-1.4 derselbe Inhalt") -> Path:
    path = root / name
    path.write_bytes(content)
    return path


class TestRegisteringAFile:
    def test_the_first_sighting_creates_a_document(self, session, tmp_path):
        document_id = registry.register_file(session, _pdf(tmp_path, "WD 3-029-23.pdf"), tmp_path)

        assert document_id is not None
        assert len(session.execute(select(Document)).scalars().all()) == 1

    def test_the_same_file_again_is_the_same_document(self, session, tmp_path):
        path = _pdf(tmp_path, "WD 3-029-23.pdf")

        first = registry.register_file(session, path, tmp_path)
        second = registry.register_file(session, path, tmp_path)

        assert first == second

    def test_a_renamed_file_is_still_the_same_document(self, session, tmp_path):
        """The bug, stated as a property. The flattening of `data/` renamed
        files, and every renamed document was indexed twice — once under each
        name — with the first copy left behind pointing at a file that no
        longer exists."""
        before = registry.register_file(session, _pdf(tmp_path, "alt.pdf"), tmp_path)

        after = registry.register_file(session, _pdf(tmp_path, "neu.pdf"), tmp_path)

        assert after == before
        assert len(session.execute(select(Document)).scalars().all()) == 1

    def test_and_the_registry_records_the_new_name(self, session, tmp_path):
        """So that a rename is distinguishable from a disappearance, which is
        the difference between a document to re-index and one to remove."""
        registry.register_file(session, _pdf(tmp_path, "alt.pdf"), tmp_path)

        registry.register_file(session, _pdf(tmp_path, "neu.pdf"), tmp_path)

        document = session.execute(select(Document)).scalar_one()
        assert document.original_name == "neu.pdf"
        assert {f.original_name for f in document.files} == {"alt.pdf", "neu.pdf"}

    def test_different_contents_are_different_documents(self, session, tmp_path):
        first = registry.register_file(session, _pdf(tmp_path, "a.pdf", b"eins"), tmp_path)

        second = registry.register_file(session, _pdf(tmp_path, "b.pdf", b"zwei"), tmp_path)

        assert first != second

    def test_a_file_the_scan_already_saw_is_not_duplicated(self, session, tmp_path):
        """Both entry points identify a document the same way, so ingestion
        recognises what the scan recorded rather than writing a second row."""
        _pdf(tmp_path, "WD 3-029-23.pdf")
        registry.scan(session, tmp_path)

        registry.register_file(session, tmp_path / "WD 3-029-23.pdf", tmp_path)

        assert len(session.execute(select(Document)).scalars().all()) == 1


class _FakeCollection:
    """Enough of a collection to record what was written and deleted."""

    def __init__(self):
        self.deleted: list[dict] = []
        self.points: list = []

    def delete_by_filter(self, point_filter):
        for condition in point_filter.must:
            self.deleted.append({condition.key: condition.match.value})

    def upsert(self, points):
        self.points = points
        return len(points)


def _chunk(index: int) -> Chunk:
    return Chunk(
        text=f"Abschnitt {index}",
        section_title=f"{index}. Teil",
        section_path=str(index),
        chunk_index=index,
        metadata=DocumentMetadata(
            aktenzeichen="WD 3 - 3000 - 029/23",
            fachbereich_number="WD 3",
            fachbereich="Verfassung",
            document_type="Ausarbeitung",
            title="Redezeit",
            completion_date="2023-05-08",
            language="de",
            source_file="WD 3-029-23.pdf",
        ),
    )


def _store_with(collection):
    from sentra.rag.store import VectorStore

    store = VectorStore.__new__(VectorStore)
    store._chunks = collection  # type: ignore[attr-defined]
    return store


class TestWhatGetsWritten:
    def test_a_point_is_keyed_on_the_document(self):
        collection = _FakeCollection()

        _store_with(collection).upsert_chunks([_chunk(0)], [[0.1]], document_id="doc-1")

        assert collection.points[0].id == uuid5(NAMESPACE_URL, "doc-1::0").hex

    def test_so_the_same_document_under_a_new_name_replaces_itself(self):
        """The property that stops orphans being created. Two runs, two
        filenames, one document: the ids match, so the second write lands on
        the first one's points."""
        first, second = _FakeCollection(), _FakeCollection()

        _store_with(first).upsert_chunks([_chunk(0)], [[0.1]], document_id="doc-1")
        renamed = _chunk(0)
        renamed.metadata.source_file = "anders.pdf"
        _store_with(second).upsert_chunks([renamed], [[0.1]], document_id="doc-1")

        assert first.points[0].id == second.points[0].id

    def test_the_payload_carries_the_id_so_reads_need_no_registry(self):
        """Answering a question reads Qdrant and nothing else, and has to keep
        working when the registry is down."""
        collection = _FakeCollection()

        _store_with(collection).upsert_chunks([_chunk(0)], [[0.1]], document_id="doc-1")

        assert collection.points[0].payload["document_id"] == "doc-1"

    def test_the_old_points_are_deleted_by_filename_as_well(self):
        """Every point in the index was written under the filename scheme. A
        first run that deleted only by document id would index every document
        twice."""
        collection = _FakeCollection()

        _store_with(collection).upsert_chunks([_chunk(0)], [[0.1]], document_id="doc-1")

        assert {"document_id": "doc-1"} in collection.deleted
        assert {"source_file": "WD 3-029-23.pdf"} in collection.deleted

    def test_without_an_id_it_falls_back_to_the_filename(self):
        """So a caller that has not been taught about the registry still writes
        consistent ids rather than colliding ones."""
        collection = _FakeCollection()

        _store_with(collection).upsert_chunks([_chunk(0)], [[0.1]])

        assert collection.points[0].id == uuid5(NAMESPACE_URL, "WD 3-029-23.pdf::0").hex
