"""Re-ingesting a document replaces it, rather than adding to it.

A chunk id is the source file plus the chunk index, and an upsert overwrites
the ids it writes and leaves every other id alone. So a document that chunked
into twelve pieces and now chunks into six kept points 6 to 11 from the earlier
run: old text, old metadata, still in the index, still returned as a source.

Raising CHUNK_MAX_TOKENS is enough to cause it, and so is editing a PDF.
`force=True` never helped — it bypasses the already-indexed pre-filter, which
decides whether to parse a file, and the write underneath was always the same.

The orphan test needs a real collection, so it is integration. It writes into a
collection of its own and deletes it afterwards, so it touches neither the
operator's index nor the fixture index the rest of the tier shares.
"""

import numpy as np
import pytest
from qdrant_client import QdrantClient

from sentra.domain import Chunk, DocumentMetadata
from sentra.rag.store import VectorStore

pytestmark = pytest.mark.integration

COLLECTION = "sentra_reingestion_test"


def _metadata(source_file: str = "WD 3-029-23.pdf") -> DocumentMetadata:
    return DocumentMetadata(
        aktenzeichen="WD 3 - 3000 - 029/23",
        fachbereich_number="WD 3",
        fachbereich="Verfassung und Verwaltung",
        document_type="Sachstand",
        title="Ein Dokument",
        completion_date="2023-05-01",
        language="de",
        source_file=source_file,
    )


def _chunks(count: int, *, source_file: str = "WD 3-029-23.pdf", text: str = "alt") -> list[Chunk]:
    metadata = _metadata(source_file)
    return [
        Chunk(
            text=f"{text} Abschnitt {index}",
            section_title=f"Abschnitt {index}",
            section_path=str(index),
            chunk_index=index,
            metadata=metadata,
        )
        for index in range(count)
    ]


def _vectors(count: int, dim: int) -> list[list[float]]:
    rng = np.random.default_rng(seed=count)
    return [rng.random(dim).tolist() for _ in range(count)]


@pytest.fixture
def store(settings, require_qdrant):
    """A store pointed at a collection of its own, removed afterwards."""
    own = settings.model_copy(update={"collection_name": COLLECTION})
    store = VectorStore(own)
    store.ensure_collection()
    yield store
    QdrantClient(url=own.qdrant_url).delete_collection(COLLECTION)


def _count(settings) -> int:
    return QdrantClient(url=settings.qdrant_url).count(COLLECTION).count


class TestReChunkingToFewerPieces:
    """The reported case."""

    def test_the_surplus_points_are_gone(self, store, settings):
        dim = settings.embedding_dim
        store.upsert_chunks(_chunks(12), _vectors(12, dim))
        assert _count(settings) == 12

        store.upsert_chunks(_chunks(6, text="neu"), _vectors(6, dim))

        assert _count(settings) == 6, (
            "points 6-11 from the first ingestion are still in the collection"
        )

    def test_no_stale_text_survives(self, store, settings):
        """The consequence a user would see: an orphan is still searchable and
        still comes back as a source."""
        dim = settings.embedding_dim
        store.upsert_chunks(_chunks(12, text="veraltet"), _vectors(12, dim))

        store.upsert_chunks(_chunks(6, text="aktuell"), _vectors(6, dim))

        texts = [
            point.payload["text"]
            for point in QdrantClient(url=settings.qdrant_url).scroll(
                COLLECTION, limit=100, with_payload=True
            )[0]
        ]
        assert not any("veraltet" in text for text in texts), texts


class TestOtherDocumentsAreUntouched:
    def test_re_ingesting_one_document_leaves_the_others(self, store, settings):
        """The delete is by source_file, so it has to be narrow enough to spare
        everything else in the collection."""
        dim = settings.embedding_dim
        store.upsert_chunks(_chunks(4, source_file="a.pdf"), _vectors(4, dim))
        store.upsert_chunks(_chunks(4, source_file="b.pdf"), _vectors(4, dim))

        store.upsert_chunks(_chunks(2, source_file="a.pdf"), _vectors(2, dim))

        assert _count(settings) == 6  # 2 of a.pdf, 4 of b.pdf

    def test_a_batch_covering_several_documents_replaces_each(self, store, settings):
        dim = settings.embedding_dim
        store.upsert_chunks(_chunks(3, source_file="a.pdf"), _vectors(3, dim))
        store.upsert_chunks(_chunks(3, source_file="b.pdf"), _vectors(3, dim))

        mixed = _chunks(1, source_file="a.pdf") + _chunks(1, source_file="b.pdf")
        store.upsert_chunks(mixed, _vectors(2, dim))

        assert _count(settings) == 2


class TestTheOrdinaryCases:
    def test_a_first_ingestion_writes_everything(self, store, settings):
        store.upsert_chunks(_chunks(5), _vectors(5, settings.embedding_dim))

        assert _count(settings) == 5

    def test_re_ingesting_the_same_count_is_a_replacement(self, store, settings):
        dim = settings.embedding_dim
        store.upsert_chunks(_chunks(5, text="alt"), _vectors(5, dim))

        store.upsert_chunks(_chunks(5, text="neu"), _vectors(5, dim))

        assert _count(settings) == 5

    def test_re_chunking_to_more_pieces_still_works(self, store, settings):
        dim = settings.embedding_dim
        store.upsert_chunks(_chunks(3), _vectors(3, dim))

        store.upsert_chunks(_chunks(9), _vectors(9, dim))

        assert _count(settings) == 9
