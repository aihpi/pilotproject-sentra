import json
import logging
import threading
from datetime import UTC
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from sentra.api.models import (
    AnswerRequest,
    AnswerSourceRef,
    ConfigResponse,
    DocumentInfo,
    DocumentSearchRequest,
    DocumentSearchResponse,
    DocumentSearchResult,
    ExternalSourceResult,
    ExternalSourcesRequest,
    ExternalSourcesResponse,
    FeedbackRequest,
    FeedbackResponse,
    GeneratedAnswerResponse,
    HealthResponse,
    IngestionStatusResponse,
    IngestStartResponse,
    ReferatOption,
    SimilarDocumentsRequest,
    date_range_params,
)
from sentra.config import Settings, get_settings
from sentra.ingestion.metadata import DOCUMENT_TYPE_VALUES, FACHBEREICH_NAMES
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.generator import DEFAULT_PROMPTS, AnswerGenerator
from sentra.rag.store import VectorStore
from sentra.services import explorer
from sentra.services.ingest import get_ingestion_progress, run_ingestion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ── Dependency helpers (read shared clients from app.state) ──────────


def get_store(request: Request) -> VectorStore:
    return request.app.state.store


def get_embedder(request: Request) -> EmbeddingClient:
    return request.app.state.embedder


def get_generator(request: Request) -> AnswerGenerator:
    return request.app.state.generator


# ── Ingestion endpoints ──────────────────────────────────────────────


@router.post("/ingest", response_model=IngestStartResponse)
def ingest(
    force: bool = False,
    store: VectorStore = Depends(get_store),
    embedder: EmbeddingClient = Depends(get_embedder),
    settings: Settings = Depends(get_settings),
) -> IngestStartResponse:
    """Trigger document ingestion as a background task.

    Processes all PDFs in the configured documents directory.
    Use force=true to re-index already-indexed documents.
    Poll GET /api/ingest/status for progress.
    """
    progress = get_ingestion_progress()
    if progress.status == "running":
        raise HTTPException(status_code=409, detail="Ingestion already running")

    logger.info("Ingestion triggered via API (force=%s)", force)
    thread = threading.Thread(
        target=run_ingestion,
        args=(store, embedder, settings, force),
        daemon=True,
    )
    thread.start()

    return IngestStartResponse(status="started")


@router.get("/ingest/status", response_model=IngestionStatusResponse)
def ingest_status() -> IngestionStatusResponse:
    """Get the current ingestion progress."""
    progress = get_ingestion_progress()
    return IngestionStatusResponse(
        status=progress.status,
        total_files=progress.total_files,
        processed=progress.processed,
        skipped=progress.skipped,
        chunks_created=progress.chunks_created,
        errors=list(progress.errors),
        current_file=progress.current_file,
        started_at=progress.started_at,
        completed_at=progress.completed_at,
        stale_documents=list(progress.stale_documents),
    )


# ── Document endpoints ───────────────────────────────────────────────


@router.get("/documents", response_model=list[DocumentInfo])
def list_documents(
    store: VectorStore = Depends(get_store),
) -> list[DocumentInfo]:
    """List all indexed documents with metadata."""
    try:
        info = store.collection_info()
        if info["points_count"] == 0:
            return []
    except Exception:
        return []

    raw_docs = store.scroll_all_documents()
    return [
        DocumentInfo(
            aktenzeichen=d.aktenzeichen,
            title=d.title,
            fachbereich_number=d.fachbereich_number,
            fachbereich=d.fachbereich,
            document_type=d.document_type,
            completion_date=d.completion_date,
            language=d.language,
            source_file=d.source_file,
        )
        for d in raw_docs
    ]


@router.get("/documents/{filename}")
def serve_document(
    filename: str,
    settings: Settings = Depends(get_settings),
):
    """Serve a PDF document by filename."""
    from fastapi.responses import FileResponse

    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are served")

    file_path = Path(settings.documents_dir) / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        content_disposition_type="inline",
        filename=filename,
    )


# ── Feedback endpoint ────────────────────────────────────────────────


@router.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(
    body: FeedbackRequest,
    settings: Settings = Depends(get_settings),
) -> FeedbackResponse:
    """Record user feedback on an answer."""
    from datetime import datetime

    feedback_entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "question": body.question,
        "answer": body.answer,
        "rating": body.rating,
        "comment": body.comment,
    }

    feedback_path = Path(settings.feedback_file)
    feedback_path.parent.mkdir(parents=True, exist_ok=True)

    with open(feedback_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(feedback_entry, ensure_ascii=False) + "\n")

    logger.info("Feedback recorded: %s", body.rating)
    return FeedbackResponse(status="ok")


# ── Health endpoint ──────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
def health(
    store: VectorStore = Depends(get_store),
) -> HealthResponse:
    """Health check endpoint. Verifies Qdrant connectivity."""
    try:
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


# ── Client configuration ────────────────────────────────────────────


@router.get("/config", response_model=ConfigResponse)
def config() -> ConfigResponse:
    """The prompts and filter options the UI needs at start-up.

    All of this used to be copied into the frontend, with a comment asking
    whoever edited it to keep both copies in step. Serving it means there is
    one definition, and the UI shows the prompt that actually runs.

    Static, so it takes no dependencies and needs no Qdrant.
    """
    return ConfigResponse(
        prompts=DEFAULT_PROMPTS,
        document_types=DOCUMENT_TYPE_VALUES,
        referate=[
            ReferatOption(number=number, name=name) for number, name in FACHBEREICH_NAMES.items()
        ],
    )


# ── Explorer endpoints (v2) ─────────────────────────────────────────


@router.post("/explorer/documents", response_model=DocumentSearchResponse)
def explorer_documents(
    body: DocumentSearchRequest,
    store: VectorStore = Depends(get_store),
    embedder: EmbeddingClient = Depends(get_embedder),
) -> DocumentSearchResponse:
    """UC#1: Find documents by topic."""
    date_from, date_to = date_range_params(body.date_range)
    docs = explorer.search_documents_by_topic(
        query=body.query,
        date_from=date_from,
        date_to=date_to,
        top_k=body.top_k,
        store=store,
        embedder=embedder,
        fachbereich=body.fachbereich,
        document_type=body.document_type,
    )
    return DocumentSearchResponse(documents=[DocumentSearchResult.from_domain(d) for d in docs])


@router.post("/explorer/similar", response_model=DocumentSearchResponse)
def explorer_similar(
    body: SimilarDocumentsRequest,
    store: VectorStore = Depends(get_store),
) -> DocumentSearchResponse:
    """UC#4: Find documents similar to a given Aktenzeichen."""
    docs = explorer.find_similar_documents(
        aktenzeichen=body.aktenzeichen,
        top_k=body.top_k,
        store=store,
    )
    return DocumentSearchResponse(documents=[DocumentSearchResult.from_domain(d) for d in docs])


@router.post("/explorer/sources", response_model=ExternalSourcesResponse)
def explorer_sources(
    body: ExternalSourcesRequest,
    store: VectorStore = Depends(get_store),
    embedder: EmbeddingClient = Depends(get_embedder),
) -> ExternalSourcesResponse:
    """UC#6: Find external sources cited in documents matching a topic."""
    date_from, date_to = date_range_params(body.date_range)
    sources = explorer.find_external_sources(
        query=body.query,
        date_from=date_from,
        date_to=date_to,
        store=store,
        embedder=embedder,
        fachbereich=body.fachbereich,
        document_type=body.document_type,
    )
    return ExternalSourcesResponse(sources=[ExternalSourceResult.from_domain(s) for s in sources])


@router.post("/explorer/answer", response_model=GeneratedAnswerResponse)
def explorer_answer(
    body: AnswerRequest,
    store: VectorStore = Depends(get_store),
    embedder: EmbeddingClient = Depends(get_embedder),
    generator: AnswerGenerator = Depends(get_generator),
    settings: Settings = Depends(get_settings),
) -> GeneratedAnswerResponse:
    """UC#10: Answer a specific Fachfrage."""
    date_from, date_to = date_range_params(body.date_range)
    result = explorer.answer_question(
        query=body.query,
        date_from=date_from,
        date_to=date_to,
        top_k=body.top_k or settings.retrieval_top_k,
        store=store,
        embedder=embedder,
        generator=generator,
        fachbereich=body.fachbereich,
        document_type=body.document_type,
        system_prompt=body.system_prompt,
    )
    return GeneratedAnswerResponse(
        text=result.text,
        sources=[AnswerSourceRef.from_domain(s) for s in result.sources],
        system_prompt=result.system_prompt,
    )


@router.post("/explorer/overview", response_model=GeneratedAnswerResponse)
def explorer_overview(
    body: AnswerRequest,
    store: VectorStore = Depends(get_store),
    embedder: EmbeddingClient = Depends(get_embedder),
    generator: AnswerGenerator = Depends(get_generator),
    settings: Settings = Depends(get_settings),
) -> GeneratedAnswerResponse:
    """UC#2: Generate a structured topic overview."""
    date_from, date_to = date_range_params(body.date_range)
    result = explorer.generate_overview(
        query=body.query,
        date_from=date_from,
        date_to=date_to,
        top_k=body.top_k or settings.retrieval_top_k,
        store=store,
        embedder=embedder,
        generator=generator,
        fachbereich=body.fachbereich,
        document_type=body.document_type,
        system_prompt=body.system_prompt,
    )
    return GeneratedAnswerResponse(
        text=result.text,
        sources=[AnswerSourceRef.from_domain(s) for s in result.sources],
        system_prompt=result.system_prompt,
    )
