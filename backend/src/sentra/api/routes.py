import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

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
    FeedbackEntry,
    FeedbackRequest,
    FeedbackResponse,
    GeneratedAnswerResponse,
    HealthResponse,
    IngestionStatusResponse,
    IngestStartResponse,
    ReferatOption,
    RetrievedChunk,
    SimilarDocumentsRequest,
    date_range_params,
)
from sentra.config import Settings, get_settings
from sentra.domain import AnswerResult
from sentra.ingestion.metadata import DOCUMENT_TYPE_VALUES, FACHBEREICH_NAMES
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.generator import DEFAULT_PROMPTS, AnswerGenerator
from sentra.rag.store import VectorStore
from sentra.services import explorer
from sentra.services.ingest import get_ingestion_progress
from sentra.services.jobs import IngestionJob

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ── Dependency helpers (read shared clients from app.state) ──────────


def get_store(request: Request) -> VectorStore:
    return request.app.state.store


def get_embedder(request: Request) -> EmbeddingClient:
    return request.app.state.embedder


def get_ingestion_job(request: Request) -> IngestionJob:
    return request.app.state.ingestion_job


def get_generator(request: Request) -> AnswerGenerator:
    return request.app.state.generator


# ── Ingestion endpoints ──────────────────────────────────────────────


@router.post("/ingest", response_model=IngestStartResponse)
def ingest(
    force: bool = False,
    job: IngestionJob = Depends(get_ingestion_job),
    store: VectorStore = Depends(get_store),
    embedder: EmbeddingClient = Depends(get_embedder),
    settings: Settings = Depends(get_settings),
) -> IngestStartResponse:
    """Trigger document ingestion as a background task.

    Processes all PDFs in the configured documents directory.
    Use force=true to re-index already-indexed documents.
    Poll GET /api/ingest/status for progress.

    The job decides whether a run can start, under its own lock. All that is
    left here is turning "no" into a status code.
    """
    if not job.start(store, embedder, settings, force):
        # The one detail not in German. The frontend has its own wording for
        # this status, so this string never reaches a user, and giving it a
        # German twin here would put the same sentence in two places with
        # nothing tying them together.
        raise HTTPException(status_code=409, detail="Ingestion already running")

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
    """List all indexed documents with metadata.

    An index that does not exist yet, or exists and is empty, is an empty
    list. A Qdrant that cannot be reached is not: that used to be caught here
    and reported as an empty index, which left the frontend unable to tell the
    two apart. It now reaches the 503 handler.
    """
    if not store.collection_exists():
        return []

    if store.collection_info()["points_count"] == 0:
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
) -> FileResponse:
    """Serve a PDF document by filename."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Ungültiger Dateiname.")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Es werden nur PDF-Dateien ausgeliefert.")

    file_path = Path(settings.documents_dir) / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden.")

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
    feedback_entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "question": body.question,
        "answer": body.answer,
        "rating": body.rating,
        "comment": body.comment,
    }

    feedback_path = Path(settings.feedback_file)

    # A full or unwritable disk is a dependency failure like any other, and
    # this one surfaced as a bare 500 with a traceback. The rating is already
    # lost at this point either way; the caller at least learns it was not
    # their request that was wrong.
    try:
        feedback_path.parent.mkdir(parents=True, exist_ok=True)
        with open(feedback_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(feedback_entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("Could not write feedback to %s: %s", feedback_path, exc)
        raise HTTPException(
            status_code=503,
            detail="Rückmeldung konnte nicht gespeichert werden.",
        ) from exc

    logger.info("Feedback recorded: %s", body.rating)
    return FeedbackResponse(status="ok")


@router.get("/feedback", response_model=list[FeedbackEntry])
def list_feedback(
    rating: str | None = None,
    limit: int = 100,
    settings: Settings = Depends(get_settings),
) -> list[FeedbackEntry]:
    """Recorded feedback, newest first.

    Read back for the evaluation harness: the Vorlage asks for known problem
    cases from earlier feedback to be taken into a round on purpose, and the
    harness runs as a separate process with no access to this file.

    A malformed line is skipped rather than failing the request. The file is
    append-only and written by a different code path; one bad line should not
    make every earlier rating unreadable.
    """
    path = Path(settings.feedback_file)
    if not path.is_file():
        return []

    entries: list[FeedbackEntry] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed feedback line")
                continue
            if rating and raw.get("rating") != rating:
                continue
            entries.append(
                FeedbackEntry(
                    # Derived, not stored: see FeedbackEntry.
                    id=str(uuid5(NAMESPACE_URL, f"{raw.get('timestamp')}::{raw.get('question')}")),
                    timestamp=raw.get("timestamp", ""),
                    question=raw.get("question", ""),
                    answer=raw.get("answer", ""),
                    rating=raw.get("rating", ""),
                    comment=raw.get("comment"),
                )
            )
    except OSError as exc:
        logger.error("Could not read feedback from %s: %s", path, exc)
        raise HTTPException(
            status_code=503, detail="Rückmeldungen konnten nicht gelesen werden."
        ) from exc

    return list(reversed(entries))[:limit]


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


def _answer_response(result: AnswerResult, *, debug: bool) -> GeneratedAnswerResponse:
    """Shape a generated answer for the wire.

    Without debug the three extra fields stay None and pydantic leaves them
    out, so the response is what every existing caller already parses.
    """
    return GeneratedAnswerResponse(
        text=result.text,
        sources=[AnswerSourceRef.from_domain(s) for s in result.sources],
        system_prompt=result.system_prompt,
        hits=[RetrievedChunk.from_domain(h) for h in result.hits] if debug else None,
        finish_reason=result.finish_reason,
        model=result.model,
    )


@router.post(
    "/explorer/answer",
    response_model=GeneratedAnswerResponse,
    # Without this the three debug fields serialise as explicit nulls and every
    # existing caller sees new keys. `system_prompt` is always populated by the
    # service, on the no-results path too, so nothing a caller reads today can
    # disappear — and a test pins that, because this is the kind of setting
    # whose blast radius is invisible until something downstream breaks.
    response_model_exclude_none=True,
)
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
        debug=body.debug,
    )
    return _answer_response(result, debug=body.debug)


@router.post(
    "/explorer/overview",
    response_model=GeneratedAnswerResponse,
    response_model_exclude_none=True,
)
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
        debug=body.debug,
    )
    return _answer_response(result, debug=body.debug)
