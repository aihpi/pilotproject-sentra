import logging
from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    DatetimeRange,
    Distance,
    FieldCondition,
    Filter,
    HasIdCondition,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from sentra.config import Settings
from sentra.domain import (
    Chunk,
    DocumentMetadata,
    DocumentRecord,
    ExternalUrl,
    Hit,
    ScoredDocumentRecord,
)

logger = logging.getLogger(__name__)


class DimensionMismatch(RuntimeError):
    """An existing collection was built for a different vector width.

    Raised at startup rather than on the first search. A collection cannot serve
    vectors of a width it was not created with, so every query would fail; the
    useful moment to say so is before the application claims to be healthy.
    """


def _payload_of(point: object) -> dict:
    """The payload of a Qdrant point, as a dict.

    The client types `payload` as optional because a point can be stored without
    one. Ours never are: every upsert here writes a payload. Rather than
    scattering that assumption across the module as None checks or ignores, it is
    made once here, and a point that really has no payload degrades to empty
    rather than raising deep inside a comprehension.
    """
    return getattr(point, "payload", None) or {}


def _metadata_from_payload(payload: dict) -> DocumentMetadata:
    """Read document metadata out of a payload.

    This function and the two below are the only places that decide what happens
    when a field is missing, which is why the defaults live here and nowhere
    else. Missing strings become empty, which is what every consumer already
    assumed when it called `.get(key, "")`.
    """
    return DocumentMetadata(
        aktenzeichen=payload.get("aktenzeichen", ""),
        fachbereich_number=payload.get("fachbereich_number", ""),
        fachbereich=payload.get("fachbereich", ""),
        document_type=payload.get("document_type", ""),
        title=payload.get("title", ""),
        completion_date=payload.get("completion_date", ""),
        language=payload.get("language", ""),
        source_file=payload.get("source_file", ""),
    )


def _hit_from_point(point: object, payload: dict) -> Hit:
    """Build a Hit from a scored chunk point."""
    return Hit(
        score=getattr(point, "score", 0.0),
        text=payload.get("text", ""),
        section_title=payload.get("section_title", ""),
        section_path=payload.get("section_path", ""),
        chunk_index=payload.get("chunk_index", 0),
        aktenzeichen=payload.get("aktenzeichen", ""),
        fachbereich_number=payload.get("fachbereich_number", ""),
        fachbereich=payload.get("fachbereich", ""),
        document_type=payload.get("document_type", ""),
        title=payload.get("title", ""),
        completion_date=payload.get("completion_date", ""),
        language=payload.get("language", ""),
        source_file=payload.get("source_file", ""),
    )


def _record_from_payload(payload: dict) -> DocumentRecord:
    """Build a DocumentRecord from a doc-summary payload."""
    return DocumentRecord(
        metadata=_metadata_from_payload(payload),
        urls=[
            ExternalUrl(
                url=u.get("url", ""),
                label=u.get("label", ""),
                context=u.get("context", ""),
            )
            for u in payload.get("urls", [])
        ],
    )


UPSERT_BATCH_SIZE = 100

# The two collections are paged differently on purpose. A chunk payload carries
# the full chunk text, so those pages are kept small; the doc-summary scans ask
# for a single field, so they can be much larger.
CHUNK_SCROLL_PAGE_SIZE = 100
DOC_SCROLL_PAGE_SIZE = 1000

CHUNK_INDEXED_FIELDS = (
    "fachbereich_number",
    "document_type",
    "language",
    "aktenzeichen",
)
DOC_INDEXED_FIELDS = (
    "aktenzeichen",
    "fachbereich_number",
    "document_type",
)


class _Collection:
    """One Qdrant collection, holding the mechanics both of ours shared.

    VectorStore keeps two of these. What differs between the chunk collection and
    the doc-summary collection stays in VectorStore; what was copied between them
    lives here once.
    """

    def __init__(
        self,
        client: QdrantClient,
        name: str,
        indexed_fields: tuple[str, ...],
        vector_size: int,
    ) -> None:
        self._client = client
        self.name = name
        self._indexed_fields = indexed_fields
        self._vector_size = vector_size

    def _names(self) -> set[str]:
        return {c.name for c in self._client.get_collections().collections}

    def exists(self) -> bool:
        """Whether the collection is there, False if Qdrant cannot be reached.

        Tolerant on purpose: callers use this to decide whether there is
        anything to read yet, and "not reachable" and "not created" lead to the
        same empty answer. `ensure` deliberately does not use it, so that a
        startup against a dead Qdrant still fails loudly.
        """
        try:
            return self.name in self._names()
        except Exception:
            return False

    def ensure(self) -> None:
        """Create the collection and its payload indexes if it is missing."""
        if self.name in self._names():
            logger.info("Collection '%s' already exists", self.name)
            return

        self._client.create_collection(
            collection_name=self.name,
            vectors_config=VectorParams(size=self._vector_size, distance=Distance.COSINE),
        )
        for field in self._indexed_fields:
            self._client.create_payload_index(
                collection_name=self.name,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        logger.info(
            "Created collection '%s' with payload indexes on %s",
            self.name,
            ", ".join(self._indexed_fields),
        )

    def upsert(self, points: list[PointStruct]) -> int:
        """Write points in batches. Returns how many were written."""
        for i in range(0, len(points), UPSERT_BATCH_SIZE):
            batch = points[i : i + UPSERT_BATCH_SIZE]
            self._client.upsert(collection_name=self.name, wait=True, points=batch)
            logger.debug("Upserted batch %d-%d / %d", i, i + len(batch), len(points))

        logger.info("Upserted %d points into '%s'", len(points), self.name)
        return len(points)

    def scroll(
        self,
        *,
        page_size: int,
        with_payload: bool | list[str] = True,
    ) -> Iterator[Any]:
        """Yield every point, paging through the collection."""
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=self.name,
                limit=page_size,
                offset=offset,
                with_payload=with_payload,
                with_vectors=False,
            )
            yield from points
            if offset is None:
                return

    def configured_vector_size(self) -> int | None:
        """The width this collection was created with, or None if it is absent."""
        if not self.exists():
            return None
        params = self._client.get_collection(collection_name=self.name).config.params
        vectors = params.vectors
        return getattr(vectors, "size", None)

    def verify_vector_size(self) -> None:
        """Refuse to continue if the collection cannot hold our vectors."""
        actual = self.configured_vector_size()
        if actual is not None and actual != self._vector_size:
            raise DimensionMismatch(
                f"Collection '{self.name}' was created for {actual}-dimensional "
                f"vectors but EMBEDDING_DIM is {self._vector_size}. The embedding "
                f"model was probably changed. Either set EMBEDDING_DIM back, or "
                f"delete the collection and re-ingest."
            )

    def delete(self) -> None:
        self._client.delete_collection(collection_name=self.name)
        logger.info("Deleted collection '%s'", self.name)

    def info(self) -> dict:
        info = self._client.get_collection(collection_name=self.name)
        return {
            "name": self.name,
            "points_count": info.points_count,
            "indexed_vectors_count": info.indexed_vectors_count,
            "status": info.status.value,
        }


class VectorStore:
    """Qdrant vector store for Bundestag document chunks."""

    def __init__(self, settings: Settings) -> None:
        self._client = QdrantClient(url=settings.qdrant_url)
        self._chunks = _Collection(
            self._client,
            settings.collection_name,
            CHUNK_INDEXED_FIELDS,
            settings.embedding_dim,
        )
        self._docs = _Collection(
            self._client,
            settings.doc_collection_name,
            DOC_INDEXED_FIELDS,
            settings.embedding_dim,
        )

    def verify_dimensions(self) -> None:
        """Check both collections can hold vectors of the configured width.

        Costs one call per collection and no embedding, because it compares the
        configured width against what Qdrant already recorded when the
        collection was created.
        """
        self._chunks.verify_vector_size()
        self._docs.verify_vector_size()

    def ensure_collection(self) -> None:
        """Create the chunk collection if it doesn't exist."""
        self._chunks.ensure()

    def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> int:
        """Insert chunk embeddings and metadata into Qdrant.

        Returns the number of points upserted.
        """
        # Point ID is derived from source_file (not aktenzeichen) because
        # _Abstract pairs and multi-AZ documents can share an Aktenzeichen,
        # but the filename is always unique on disk.
        points = [
            PointStruct(
                id=uuid5(
                    NAMESPACE_URL,
                    f"{chunk.metadata.source_file}::{chunk.chunk_index}",
                ).hex,
                vector=embedding,
                payload={
                    "text": chunk.text,
                    "section_title": chunk.section_title,
                    "section_path": chunk.section_path,
                    "chunk_index": chunk.chunk_index,
                    "aktenzeichen": chunk.metadata.aktenzeichen,
                    "fachbereich_number": chunk.metadata.fachbereich_number,
                    "fachbereich": chunk.metadata.fachbereich,
                    "document_type": chunk.metadata.document_type,
                    "title": chunk.metadata.title,
                    "completion_date": chunk.metadata.completion_date,
                    "language": chunk.metadata.language,
                    "source_file": chunk.metadata.source_file,
                },
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]

        return self._chunks.upsert(points)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        fachbereich: str | None = None,
        document_type: str | None = None,
        language: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[Hit]:
        """Search for similar chunks with optional metadata filtering.

        Returns a list of dicts with 'score' and all payload fields.
        date_from/date_to are year strings ("2023") converted to ISO range.
        """
        # The three keyword filters differ only in which payload key they match,
        # so they are one loop. Each is applied only when a value was given.
        conditions: list[FieldCondition] = [
            FieldCondition(key=key, match=MatchValue(value=value))
            for key, value in (
                ("fachbereich_number", fachbereich),
                ("document_type", document_type),
                ("language", language),
            )
            if value
        ]
        if date_from or date_to:
            try:
                gte = date(int(date_from), 1, 1) if date_from else None
                lte = date(int(date_to), 12, 31) if date_to else None
            except (ValueError, TypeError):
                logger.warning(
                    "Invalid date_from=%r / date_to=%r, skipping date filter",
                    date_from,
                    date_to,
                )
            else:
                conditions.append(
                    FieldCondition(
                        key="completion_date",
                        range=DatetimeRange(gte=gte, lte=lte),
                    )
                )

        query_filter = Filter(must=conditions) if conditions else None

        results = self._client.query_points(
            collection_name=self._chunks.name,
            query=query_embedding,
            query_filter=query_filter,
            with_payload=True,
            limit=top_k,
        ).points

        return [_hit_from_point(point, _payload_of(point)) for point in results]

    def scroll_all_documents(self) -> list[DocumentMetadata]:
        """Scroll all chunks and return each document once, by source_file."""
        seen: set[str] = set()
        documents: list[DocumentMetadata] = []
        for point in self._chunks.scroll(page_size=CHUNK_SCROLL_PAGE_SIZE):
            payload = _payload_of(point)
            source_file = payload.get("source_file", "")
            if source_file and source_file not in seen:
                seen.add(source_file)
                documents.append(_metadata_from_payload(payload))
        return documents

    def delete_collection(self) -> None:
        """Delete the collection (useful for re-ingestion)."""
        self._chunks.delete()

    def collection_info(self) -> dict:
        """Get collection statistics."""
        return self._chunks.info()

    # ── Document-level collection ────────────────────────────────────

    def ensure_doc_collection(self) -> None:
        """Create the document-level collection if it doesn't exist."""
        self._docs.ensure()

    def upsert_doc_records(
        self,
        records: list[dict],
        embeddings: list[list[float]],
    ) -> int:
        """Insert document-level records (one per document).

        Each record dict must have at least 'source_file' (used as unique ID)
        and 'aktenzeichen' (kept for filtering).
        Returns the number of points upserted.
        """
        points = [
            PointStruct(
                id=uuid5(NAMESPACE_URL, f"doc::{rec['source_file']}").hex,
                vector=emb,
                payload=rec,
            )
            for rec, emb in zip(records, embeddings, strict=True)
        ]

        return self._docs.upsert(points)

    def search_similar_docs(
        self,
        aktenzeichen: str,
        top_k: int = 10,
    ) -> list[ScoredDocumentRecord]:
        """Find documents similar to the given Aktenzeichen.

        Looks up the document embedding via payload filter (since multiple
        documents can share the same Aktenzeichen — e.g., Abstract pairs),
        then searches for nearest neighbors (excluding itself).
        """
        # Find the source point by aktenzeichen field
        matches, _ = self._client.scroll(
            collection_name=self._docs.name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="aktenzeichen",
                        match=MatchValue(value=aktenzeichen),
                    )
                ]
            ),
            limit=1,
            with_vectors=True,
            with_payload=True,
        )
        if not matches:
            logger.warning("Document '%s' not found in doc collection", aktenzeichen)
            return []

        doc_vector = matches[0].vector
        self_id = matches[0].id
        if not isinstance(doc_vector, list):
            # The client allows a named-vector mapping or no vector at all; this
            # collection is created with a single unnamed vector, so anything
            # else means the point was not written by us.
            logger.warning(
                "Document '%s' has no single unnamed vector to compare against",
                aktenzeichen,
            )
            return []

        # Search for similar docs, excluding self
        results = self._client.query_points(
            collection_name=self._docs.name,
            query=doc_vector,
            query_filter=Filter(must_not=[HasIdCondition(has_id=[self_id])]),
            with_payload=True,
            limit=top_k,
        ).points

        return [
            ScoredDocumentRecord(
                score=point.score,
                record=_record_from_payload(_payload_of(point)),
            )
            for point in results
        ]

    def get_doc_records_by_aktenzeichen(self, aktenzeichen_list: list[str]) -> list[DocumentRecord]:
        """Retrieve document records by their Aktenzeichen values.

        Uses a payload filter scroll because multiple documents may share
        the same Aktenzeichen (e.g., the Ausarbeitung and its _Abstract
        version share an AZ but live under different filenames).
        """
        if not aktenzeichen_list:
            return []

        points, _ = self._client.scroll(
            collection_name=self._docs.name,
            scroll_filter=Filter(
                should=[
                    FieldCondition(
                        key="aktenzeichen",
                        match=MatchValue(value=az),
                    )
                    for az in aktenzeichen_list
                ]
            ),
            limit=max(len(aktenzeichen_list) * 2, 100),
            with_vectors=False,
            with_payload=True,
        )
        return [_record_from_payload(_payload_of(point)) for point in points]

    def get_indexed_aktenzeichen(self) -> set[str]:
        """Get all aktenzeichen values from the doc collection."""
        return self._scroll_doc_field("aktenzeichen")

    def get_indexed_source_files(self) -> set[str]:
        """Get all source_file values from the doc collection.

        Used as the skip-filter signal during incremental ingestion: the
        filename is the only intrinsically-unique identifier (Aktenzeichen
        can collide across _Abstract pairs and multi-AZ documents).
        """
        return self._scroll_doc_field("source_file")

    def _scroll_doc_field(self, field: str) -> set[str]:
        """Scroll the doc collection and collect all values of one payload field."""
        if not self._docs.exists():
            # Nothing ingested yet, or Qdrant is unreachable. Either way there
            # is nothing to skip, which is what an empty set means here.
            return set()

        values: set[str] = set()
        for point in self._docs.scroll(page_size=DOC_SCROLL_PAGE_SIZE, with_payload=[field]):
            value = _payload_of(point).get(field, "")
            if value:
                values.add(value)
        return values

    def delete_doc_collection(self) -> None:
        """Delete the document-level collection."""
        self._docs.delete()

    @staticmethod
    def mean_embedding(embeddings: list[list[float]]) -> list[float]:
        """Compute the mean of a list of embeddings."""
        arr = np.array(embeddings, dtype=np.float32)
        return arr.mean(axis=0).tolist()
