import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sentra.ingestion.chunker import Chunk, chunk_document
from sentra.ingestion.metadata import extract_metadata
from sentra.ingestion.parser import parse_pdfs
from sentra.ingestion.urls import extract_urls
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.store import VectorStore

logger = logging.getLogger(__name__)

# Filename pattern for quick AZ derivation (avoids Docling for skip check)
_FILENAME_AZ_RE = re.compile(r"((?:WD|EU)\s*\d+)-(\d+)-(\d+)")


@dataclass
class IngestionProgress:
    """Tracks progress of a background ingestion run."""

    status: str = "idle"  # idle | running | completed | failed
    total_files: int = 0
    processed: int = 0
    skipped: int = 0
    chunks_created: int = 0
    errors: list[str] = field(default_factory=list)
    current_file: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    stale_documents: list[str] = field(default_factory=list)


_progress = IngestionProgress()


def get_ingestion_progress() -> IngestionProgress:
    """Return the current ingestion progress (module-level singleton)."""
    return _progress


def _az_from_filename(filename: str) -> str | None:
    """Quickly derive aktenzeichen from filename without Docling."""
    match = _FILENAME_AZ_RE.search(filename)
    if match:
        fb = re.sub(r"(WD|EU)(\d)", r"\1 \2", match.group(1).strip())
        return f"{fb} - 3000 - {match.group(2)}/{match.group(3)}"
    return None


def run_ingestion(
    store: VectorStore,
    embedder: EmbeddingClient,
    documents_dir: str,
    force: bool = False,
) -> None:
    """Run the full document ingestion pipeline as a background task.

    Pipeline: for each PDF → Docling → metadata → chunk → embed → Qdrant
    Processes one document at a time to limit memory usage.
    Skips already-indexed documents unless force=True.
    """
    global _progress
    _progress = IngestionProgress(
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    try:
        _run_ingestion_inner(store, embedder, documents_dir, force)
    except Exception as e:
        msg = f"Ingestion failed: {e}"
        logger.exception(msg)
        _progress.errors.append(msg)
        _progress.status = "failed"
        _progress.completed_at = datetime.now(timezone.utc).isoformat()
        return

    _progress.status = "completed"
    _progress.completed_at = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Ingestion complete: %d processed, %d skipped, %d chunks, %d errors",
        _progress.processed,
        _progress.skipped,
        _progress.chunks_created,
        len(_progress.errors),
    )


def _run_ingestion_inner(
    store: VectorStore,
    embedder: EmbeddingClient,
    documents_dir: str,
    force: bool,
) -> None:
    """Inner ingestion logic — processes documents one by one."""
    # Load already-indexed aktenzeichen for incremental skip
    indexed_az: set[str] = set()
    if not force:
        indexed_az = store.get_indexed_aktenzeichen()
        if indexed_az:
            logger.info("Found %d already-indexed documents", len(indexed_az))

    store.ensure_collection()
    store.ensure_doc_collection()

    # Count total files and pre-filter for incremental ingestion
    from pathlib import Path
    pdf_dir = Path(documents_dir)
    all_pdf_paths = sorted(pdf_dir.glob("*.pdf"))

    if not all_pdf_paths:
        _progress.errors.append("No PDF files found")
        return

    # Pre-filter: skip files whose AZ (derived from filename) is already indexed.
    # This avoids expensive Docling parsing for already-indexed documents.
    paths_to_process: list[Path] = []
    filesystem_az: set[str] = set()

    for p in all_pdf_paths:
        az = _az_from_filename(p.name)
        if az:
            filesystem_az.add(az)
        if not force and az and az in indexed_az:
            _progress.skipped += 1
            logger.info("Skipping %s (%s, already indexed)", p.name, az)
        else:
            paths_to_process.append(p)

    _progress.total_files = len(all_pdf_paths)

    if not paths_to_process:
        logger.info("All %d documents already indexed, nothing to do", len(all_pdf_paths))
        return

    logger.info(
        "%d new files to process (%d skipped as already indexed)",
        len(paths_to_process),
        _progress.skipped,
    )

    for doc in parse_pdfs(documents_dir, pdf_paths=paths_to_process):
        doc_start = time.monotonic()
        _progress.current_file = doc.source_file

        try:
            # Extract metadata
            metadata = extract_metadata(
                doc.markdown, doc.furniture_text, doc.source_file, doc.pdf_metadata
            )

            filesystem_az.add(metadata.aktenzeichen)

            # Chunk
            chunks = chunk_document(doc.markdown, metadata)

            if not chunks:
                _progress.processed += 1
                logger.warning("No chunks produced for %s", doc.source_file)
                continue

            # Embed this document's chunks
            texts = [chunk.text for chunk in chunks]
            embeddings = embedder.embed_documents(texts)

            # Upsert chunks to Qdrant
            store.upsert_chunks(chunks, embeddings)
            _progress.chunks_created += len(chunks)

            # Build and store doc-level record
            _store_doc_record(store, embedder, chunks, embeddings, metadata, doc.markdown)

            elapsed = time.monotonic() - doc_start
            _progress.processed += 1
            logger.info(
                "[%d/%d] %s → %s: %d chunks (%.1fs)",
                _progress.processed + _progress.skipped,
                _progress.total_files,
                doc.source_file,
                metadata.aktenzeichen,
                len(chunks),
                elapsed,
            )

        except Exception as e:
            msg = f"Failed to process {doc.source_file}: {e}"
            logger.exception(msg)
            _progress.errors.append(msg)
            _progress.processed += 1

    _progress.current_file = ""

    # Detect stale documents (in Qdrant but not on filesystem)
    if indexed_az and filesystem_az:
        stale = indexed_az - filesystem_az
        if stale:
            _progress.stale_documents = sorted(stale)
            logger.warning(
                "Found %d stale documents in Qdrant not on filesystem: %s",
                len(stale),
                ", ".join(sorted(stale)[:10]),
            )


def _store_doc_record(
    store: VectorStore,
    embedder: EmbeddingClient,
    chunks: list[Chunk],
    embeddings: list[list[float]],
    metadata,
    markdown: str,
) -> None:
    """Compute doc-level mean embedding, extract URLs, and store a single doc record."""
    mean_emb = VectorStore.mean_embedding(embeddings)

    urls = extract_urls(markdown)
    url_records = [
        {"url": u.url, "label": u.label, "context": u.context} for u in urls
    ]

    record = {
        "aktenzeichen": metadata.aktenzeichen,
        "title": metadata.title,
        "fachbereich_number": metadata.fachbereich_number,
        "fachbereich": metadata.fachbereich,
        "document_type": metadata.document_type,
        "completion_date": metadata.completion_date,
        "language": metadata.language,
        "source_file": metadata.source_file,
        "urls": url_records,
    }

    store.upsert_doc_records([record], [mean_emb])
