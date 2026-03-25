import logging
from datetime import date
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
from sentra.ingestion.chunker import Chunk

logger = logging.getLogger(__name__)

# Octen-Embedding-8B embedding dimension
EMBEDDING_DIM = 4096


class VectorStore:
    """Qdrant vector store for Bundestag document chunks."""

    def __init__(self, settings: Settings) -> None:
        self._client = QdrantClient(url=settings.qdrant_url)
        self._collection = settings.collection_name
        self._doc_collection = settings.doc_collection_name

    def ensure_collection(self) -> None:
        """Create the collection if it doesn't exist."""
        collections = self._client.get_collections().collections
        if any(c.name == self._collection for c in collections):
            logger.info("Collection '%s' already exists", self._collection)
            return

        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=VectorParams(
                size=EMBEDDING_DIM,
                distance=Distance.COSINE,
            ),
        )

        # Create payload indexes for filtered search
        for field, schema_type in [
            ("fachbereich_number", PayloadSchemaType.KEYWORD),
            ("document_type", PayloadSchemaType.KEYWORD),
            ("language", PayloadSchemaType.KEYWORD),
            ("aktenzeichen", PayloadSchemaType.KEYWORD),
        ]:
            self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field,
                field_schema=schema_type,
            )

        logger.info("Created collection '%s' with payload indexes", self._collection)

    def upsert_chunks(
        self, chunks: list[Chunk], embeddings: list[list[float]]
    ) -> int:
        """Insert chunk embeddings and metadata into Qdrant.

        Returns the number of points upserted.
        """
        points = [
            PointStruct(
                id=uuid5(
                    NAMESPACE_URL,
                    f"{chunk.metadata.aktenzeichen}::{chunk.chunk_index}",
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
            for chunk, embedding in zip(chunks, embeddings)
        ]

        # Upsert in batches of 100
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            self._client.upsert(
                collection_name=self._collection,
                wait=True,
                points=batch,
            )
            logger.debug("Upserted batch %d-%d / %d", i, i + len(batch), len(points))

        logger.info("Upserted %d points into '%s'", len(points), self._collection)
        return len(points)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        fachbereich: str | None = None,
        document_type: str | None = None,
        language: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        """Search for similar chunks with optional metadata filtering.

        Returns a list of dicts with 'score' and all payload fields.
        date_from/date_to are year strings ("2023") converted to ISO range.
        """
        conditions = []
        if fachbereich:
            conditions.append(
                FieldCondition(
                    key="fachbereich_number",
                    match=MatchValue(value=fachbereich),
                )
            )
        if document_type:
            conditions.append(
                FieldCondition(
                    key="document_type",
                    match=MatchValue(value=document_type),
                )
            )
        if language:
            conditions.append(
                FieldCondition(
                    key="language",
                    match=MatchValue(value=language),
                )
            )
        if date_from or date_to:
            try:
                gte = date(int(date_from), 1, 1) if date_from else None
                lte = date(int(date_to), 12, 31) if date_to else None
            except (ValueError, TypeError):
                logger.warning("Invalid date_from=%r / date_to=%r, skipping date filter", date_from, date_to)
            else:
                conditions.append(
                    FieldCondition(
                        key="completion_date",
                        range=DatetimeRange(gte=gte, lte=lte),
                    )
                )

        query_filter = Filter(must=conditions) if conditions else None

        results = self._client.query_points(
            collection_name=self._collection,
            query=query_embedding,
            query_filter=query_filter,
            with_payload=True,
            limit=top_k,
        ).points

        return [
            {"score": point.score, **point.payload}
            for point in results
        ]

    def scroll_all_documents(self) -> list[dict]:
        """Scroll all points and return unique documents by aktenzeichen."""
        seen: set[str] = set()
        documents: list[dict] = []
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=self._collection,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                az = point.payload.get("aktenzeichen", "")
                if az not in seen:
                    seen.add(az)
                    documents.append(point.payload)
            if offset is None:
                break
        return documents

    def delete_collection(self) -> None:
        """Delete the collection (useful for re-ingestion)."""
        self._client.delete_collection(collection_name=self._collection)
        logger.info("Deleted collection '%s'", self._collection)

    def collection_info(self) -> dict:
        """Get collection statistics."""
        info = self._client.get_collection(collection_name=self._collection)
        return {
            "name": self._collection,
            "points_count": info.points_count,
            "indexed_vectors_count": info.indexed_vectors_count,
            "status": info.status.value,
        }

    # ── Document-level collection ────────────────────────────────────

    def ensure_doc_collection(self) -> None:
        """Create the document-level collection if it doesn't exist."""
        collections = self._client.get_collections().collections
        if any(c.name == self._doc_collection for c in collections):
            logger.info("Doc collection '%s' already exists", self._doc_collection)
            return

        self._client.create_collection(
            collection_name=self._doc_collection,
            vectors_config=VectorParams(
                size=EMBEDDING_DIM,
                distance=Distance.COSINE,
            ),
        )

        for field, schema_type in [
            ("aktenzeichen", PayloadSchemaType.KEYWORD),
            ("fachbereich_number", PayloadSchemaType.KEYWORD),
            ("document_type", PayloadSchemaType.KEYWORD),
        ]:
            self._client.create_payload_index(
                collection_name=self._doc_collection,
                field_name=field,
                field_schema=schema_type,
            )

        logger.info("Created doc collection '%s'", self._doc_collection)

    def upsert_doc_records(
        self,
        records: list[dict],
        embeddings: list[list[float]],
    ) -> int:
        """Insert document-level records (one per document).

        Each record dict must have at least 'aktenzeichen'.
        Returns the number of points upserted.
        """
        points = [
            PointStruct(
                id=uuid5(NAMESPACE_URL, f"doc::{rec['aktenzeichen']}").hex,
                vector=emb,
                payload=rec,
            )
            for rec, emb in zip(records, embeddings)
        ]

        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            self._client.upsert(
                collection_name=self._doc_collection,
                wait=True,
                points=batch,
            )

        logger.info("Upserted %d doc records into '%s'", len(points), self._doc_collection)
        return len(points)

    def search_similar_docs(
        self,
        aktenzeichen: str,
        top_k: int = 10,
    ) -> list[dict]:
        """Find documents similar to the given Aktenzeichen.

        Looks up the document embedding, then searches for nearest neighbors
        (excluding itself).
        """
        point_id = uuid5(NAMESPACE_URL, f"doc::{aktenzeichen}").hex

        # Retrieve the document's embedding
        points = self._client.retrieve(
            collection_name=self._doc_collection,
            ids=[point_id],
            with_vectors=True,
            with_payload=True,
        )
        if not points:
            logger.warning("Document '%s' not found in doc collection", aktenzeichen)
            return []

        doc_vector = points[0].vector

        # Search for similar docs, excluding self
        results = self._client.query_points(
            collection_name=self._doc_collection,
            query=doc_vector,
            query_filter=Filter(
                must_not=[HasIdCondition(has_id=[point_id])]
            ),
            with_payload=True,
            limit=top_k,
        ).points

        return [
            {"score": point.score, **point.payload}
            for point in results
        ]

    def get_doc_records_by_aktenzeichen(
        self, aktenzeichen_list: list[str]
    ) -> list[dict]:
        """Retrieve document records by their Aktenzeichen values."""
        point_ids = [
            uuid5(NAMESPACE_URL, f"doc::{az}").hex for az in aktenzeichen_list
        ]
        points = self._client.retrieve(
            collection_name=self._doc_collection,
            ids=point_ids,
            with_vectors=False,
            with_payload=True,
        )
        return [point.payload for point in points]

    def get_indexed_aktenzeichen(self) -> set[str]:
        """Get all aktenzeichen values from the doc collection."""
        result: set[str] = set()
        try:
            collections = self._client.get_collections().collections
            if not any(c.name == self._doc_collection for c in collections):
                return result
        except Exception:
            return result

        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=self._doc_collection,
                limit=100,
                offset=offset,
                with_payload=["aktenzeichen"],
                with_vectors=False,
            )
            for point in points:
                az = point.payload.get("aktenzeichen", "")
                if az:
                    result.add(az)
            if offset is None:
                break
        return result

    def delete_doc_collection(self) -> None:
        """Delete the document-level collection."""
        self._client.delete_collection(collection_name=self._doc_collection)
        logger.info("Deleted doc collection '%s'", self._doc_collection)

    @staticmethod
    def mean_embedding(embeddings: list[list[float]]) -> list[float]:
        """Compute the mean of a list of embeddings."""
        arr = np.array(embeddings, dtype=np.float32)
        return arr.mean(axis=0).tolist()
