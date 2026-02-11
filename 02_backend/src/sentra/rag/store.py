import logging
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
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
    ) -> list[dict]:
        """Search for similar chunks with optional metadata filtering.

        Returns a list of dicts with 'score' and all payload fields.
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
