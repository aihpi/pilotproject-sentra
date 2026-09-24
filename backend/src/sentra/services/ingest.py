import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sentra.config import Settings
from sentra.db import session_scope
from sentra.documents import registry
from sentra.domain import DocumentMetadata
from sentra.ingestion.chunker import Chunk, chunk_document
from sentra.ingestion.metadata import extract_metadata
from sentra.ingestion.parser import parse_pdfs
from sentra.ingestion.urls import extract_urls
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.store import VectorStore

logger = logging.getLogger(__name__)


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


def run_ingestion(
    store: VectorStore,
    embedder: EmbeddingClient,
    settings: Settings,
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
        started_at=datetime.now(UTC).isoformat(),
    )

    try:
        _run_ingestion_inner(store, embedder, settings, force)
    except Exception as e:
        msg = f"Ingestion failed: {e}"
        logger.exception(msg)
        _progress.errors.append(msg)
        _progress.status = "failed"
        _progress.completed_at = datetime.now(UTC).isoformat()
        return

    _progress.status = "completed"
    _progress.completed_at = datetime.now(UTC).isoformat()

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
    settings: Settings,
    force: bool,
) -> None:
    """Inner ingestion logic — processes documents one by one."""
    # Load already-indexed source files for incremental skip.
    # We key on filename (not Aktenzeichen) because:
    # 1. Filename is intrinsically unique on disk; AZ can collide
    #    (e.g. WD 6-004-25.pdf and WD 6-004-25_Abstract.pdf share the same AZ).
    # 2. Some filenames carry a different first AZ than the body
    #    (e.g. "WD 4-003-25; WD 3-003-25.pdf" has body AZ "WD 3 - 3000 - 003/25"),
    #    so a filename-derived AZ wouldn't match what's stored.
    indexed_files: set[str] = set()
    if not force:
        indexed_files = store.get_indexed_source_files()
        if indexed_files:
            logger.info("Found %d already-indexed documents", len(indexed_files))

    # Withdrawn documents are skipped whichever way the run was started.
    #
    # The skip filter above asks Qdrant what is already indexed, and a document
    # that has just been withdrawn has no points, so it looks like one that has
    # never been seen. Without this it would be parsed and re-embedded on the
    # next run, and withdrawal would last exactly until somebody pressed the
    # ingest button.
    #
    # Outside the `force` branch on purpose: force means re-embed what is in
    # the corpus, not resurrect what was taken out of it.
    with session_scope() as session:
        withdrawn = registry.withdrawn_filenames(session)
    if withdrawn:
        logger.info("Skipping %d withdrawn documents", len(withdrawn))

    store.ensure_collection()
    store.ensure_doc_collection()

    # Count total files and pre-filter for incremental ingestion
    pdf_dir = Path(settings.documents_dir)
    all_pdf_paths = sorted(pdf_dir.glob("*.pdf"))

    if not all_pdf_paths:
        _progress.errors.append("No PDF files found")
        return

    # Pre-filter: skip files already indexed (matched by filename).
    paths_to_process: list[Path] = []
    filesystem_files: set[str] = {p.name for p in all_pdf_paths}

    # Before any of the early returns below. Both sets are complete here and
    # neither changes while documents are processed, so the answer is the same
    # as it would be at the end of the run, and it is now also reported on the
    # run where it matters most: the one that finds everything already indexed
    # and processes nothing.
    _record_stale_documents(indexed_files, filesystem_files)

    for p in all_pdf_paths:
        if p.name in withdrawn:
            _progress.skipped += 1
            logger.info("Skipping %s (withdrawn)", p.name)
            continue
        if not force and p.name in indexed_files:
            _progress.skipped += 1
            logger.info("Skipping %s (already indexed)", p.name)
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

    # Which file each parsed document came from, so it can be registered.
    # parse_pdfs yields a name, and registration needs the bytes.
    paths_by_name = {path.name: path for path in paths_to_process}
    root = Path(settings.documents_dir)

    for doc in parse_pdfs(settings.documents_dir, pdf_paths=paths_to_process):
        doc_start = time.monotonic()
        _progress.current_file = doc.source_file

        try:
            # Extract metadata
            metadata = extract_metadata(
                doc.markdown, doc.furniture_text, doc.source_file, doc.pdf_metadata
            )

            # Chunk
            # Blocks rather than markdown: a chunk now carries the page and
            # paragraph it came from, and the export cannot say where anything
            # was. Metadata extraction above still reads the markdown, which is
            # why both are on ParsedDocument.
            chunks = chunk_document(doc.blocks, metadata, max_tokens=settings.chunk_max_tokens)

            if not chunks:
                _progress.processed += 1
                logger.warning("No chunks produced for %s", doc.source_file)
                continue

            # Embed this document's chunks
            texts = [chunk.text for chunk in chunks]
            embeddings = embedder.embed_documents(texts)

            # The document's identity, from the registry. Qdrant is derived
            # from it: a point keyed on a filename cannot survive a rename, and
            # seventeen documents are indexed with no file behind them because
            # of exactly that (#140, #187).
            #
            # A hard dependency, deliberately. A document with no row has no
            # identity, and inventing one per run would put us back where we
            # started — so this fails the file loudly rather than falling back
            # to the filename, which would write points under a second identity
            # scheme that nobody would notice until the next rename.
            source_path = paths_by_name.get(doc.source_file)
            if source_path is None:
                # Should not happen — the names come from the paths we passed
                # in — but a document with no file has no identity, and
                # guessing one is the mistake this whole change removes.
                _progress.errors.append(f"{doc.source_file}: keine Datei zugeordnet")
                _progress.processed += 1
                continue

            with session_scope() as session:
                document_id = str(registry.register_file(session, source_path, root))

            # Upsert chunks to Qdrant
            store.upsert_chunks(chunks, embeddings, document_id=document_id)
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


def _record_stale_documents(indexed_files: set[str], filesystem_files: set[str]) -> None:
    """Report documents that are in Qdrant with no matching file on disk.

    Deliberately takes the two sets rather than reading them itself, so that
    it cannot end up depending on where in the run it is called from. It used
    to sit at the end of run_ingestion, after a return that fires whenever
    every file is already indexed, which is the steady state: the check went
    four months without running.

    Stays silent when either set is empty. An empty index has nothing to be
    stale, and an empty directory means the documents are not where we are
    looking, which would otherwise report every indexed document as stale.
    That covers a forced run too, where indexed_files is never loaded.
    """
    if not indexed_files or not filesystem_files:
        return

    stale = indexed_files - filesystem_files
    if not stale:
        return

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
    metadata: DocumentMetadata,
    markdown: str,
) -> None:
    """Compute doc-level mean embedding, extract URLs, and store a single doc record."""
    mean_emb = VectorStore.mean_embedding(embeddings)

    urls = extract_urls(markdown)
    url_records = [{"url": u.url, "label": u.label, "context": u.context} for u in urls]

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
