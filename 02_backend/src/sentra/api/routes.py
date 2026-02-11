import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from sentra.api.models import (
    DocumentInfo,
    HealthResponse,
    IngestResponse,
    QueryRequest,
    QueryResponse,
    SourceResponse,
)
from sentra.config import Settings, get_settings
from sentra.rag.store import VectorStore
from sentra.services.ingest import run_ingestion
from sentra.services.query import run_query, run_query_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/query", response_model=QueryResponse)
async def query(
    request: Request,
    body: QueryRequest,
    settings: Settings = Depends(get_settings),
) -> QueryResponse | StreamingResponse:
    """RAG query endpoint.

    Accepts a question and optional filters. Returns an answer with source citations.
    Supports SSE streaming when Accept: text/event-stream header is set.
    """
    # Check if client wants streaming
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return _stream_response(body, settings)

    result = run_query(
        question=body.question,
        settings=settings,
        fachbereich=body.fachbereich,
        document_type=body.document_type,
        top_k=body.top_k,
    )

    return QueryResponse(
        answer=result.answer,
        sources=[
            SourceResponse(
                aktenzeichen=s.aktenzeichen,
                title=s.title,
                section_title=s.section_title,
                fachbereich=s.fachbereich,
                score=s.score,
                text_preview=s.text_preview,
            )
            for s in result.sources
        ],
    )


def _stream_response(body: QueryRequest, settings: Settings) -> StreamingResponse:
    """Generate an SSE streaming response."""

    async def event_stream():
        stream, sources = run_query_stream(
            question=body.question,
            settings=settings,
            fachbereich=body.fachbereich,
            document_type=body.document_type,
            top_k=body.top_k,
        )

        # Send sources first
        sources_data = [
            {
                "aktenzeichen": s.aktenzeichen,
                "title": s.title,
                "section_title": s.section_title,
                "fachbereich": s.fachbereich,
                "score": s.score,
                "text_preview": s.text_preview,
            }
            for s in sources
        ]
        yield f"event: sources\ndata: {json.dumps(sources_data, ensure_ascii=False)}\n\n"

        # Stream answer tokens
        for token in stream:
            yield f"event: token\ndata: {json.dumps({'text': token}, ensure_ascii=False)}\n\n"

        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    settings: Settings = Depends(get_settings),
) -> IngestResponse:
    """Trigger document ingestion.

    Processes all PDFs in the configured documents directory.
    """
    logger.info("Ingestion triggered via API")
    result = run_ingestion(settings)

    return IngestResponse(
        documents_processed=result["documents_processed"],
        chunks_created=result["chunks_created"],
        errors=result["errors"],
    )


@router.get("/documents", response_model=list[DocumentInfo])
async def list_documents(
    settings: Settings = Depends(get_settings),
) -> list[DocumentInfo]:
    """List all indexed documents with metadata.

    Retrieves unique documents from Qdrant by scrolling through all points
    and deduplicating by Aktenzeichen.
    """
    store = VectorStore(settings)
    try:
        info = store.collection_info()
        if info["points_count"] == 0:
            return []
    except Exception:
        return []

    # Scroll through all points to collect unique documents
    seen: set[str] = set()
    documents: list[DocumentInfo] = []

    offset = None
    while True:
        points, offset = store._client.scroll(
            collection_name=settings.collection_name,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        for point in points:
            az = point.payload.get("aktenzeichen", "")
            if az in seen:
                continue
            seen.add(az)
            documents.append(
                DocumentInfo(
                    aktenzeichen=az,
                    title=point.payload.get("title", ""),
                    fachbereich_number=point.payload.get("fachbereich_number", ""),
                    fachbereich=point.payload.get("fachbereich", ""),
                    document_type=point.payload.get("document_type", ""),
                    completion_date=point.payload.get("completion_date", ""),
                    language=point.payload.get("language", ""),
                    source_file=point.payload.get("source_file", ""),
                )
            )

        if offset is None:
            break

    return documents


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Health check endpoint. Verifies Qdrant connectivity."""
    try:
        store = VectorStore(settings)
        collection = store.collection_info()
        return HealthResponse(
            status="healthy",
            qdrant="connected",
            collection=collection,
        )
    except Exception as e:
        return HealthResponse(
            status="degraded",
            qdrant=f"error: {e}",
        )
