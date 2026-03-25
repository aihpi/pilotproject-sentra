import logging
from collections import defaultdict

from sentra.config import Settings
from sentra.ingestion.chunker import Chunk, chunk_document
from sentra.ingestion.metadata import DocumentMetadata, extract_metadata
from sentra.ingestion.parser import parse_pdfs
from sentra.ingestion.urls import extract_urls
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.store import VectorStore

logger = logging.getLogger(__name__)


def run_ingestion(settings: Settings) -> dict:
    """Run the full document ingestion pipeline.

    Pipeline: PDF → Docling → metadata extraction → chunking → embedding → Qdrant
              → document-level embeddings + URL extraction → doc collection

    Returns a summary dict with counts and any errors.
    """
    errors: list[str] = []

    # 1. Parse PDFs with Docling
    logger.info("Step 1/5: Parsing PDFs from %s", settings.documents_dir)
    parsed_docs = parse_pdfs(settings.documents_dir)
    if not parsed_docs:
        return {
            "documents_processed": 0,
            "chunks_created": 0,
            "errors": ["No PDF files found or all failed to parse"],
        }

    # 2. Extract metadata, chunk, and extract URLs from each document
    logger.info("Step 2/5: Extracting metadata and chunking %d documents", len(parsed_docs))
    all_chunks: list[Chunk] = []
    doc_metadata: dict[str, DocumentMetadata] = {}
    doc_markdowns: dict[str, str] = {}

    for doc in parsed_docs:
        try:
            metadata = extract_metadata(
                doc.markdown, doc.furniture_text, doc.source_file, doc.pdf_metadata
            )
            chunks = chunk_document(
                doc.markdown, metadata, max_tokens=settings.chunk_max_tokens
            )
            all_chunks.extend(chunks)
            doc_metadata[metadata.aktenzeichen] = metadata
            doc_markdowns[metadata.aktenzeichen] = doc.markdown
            logger.info(
                "  %s: %s → %d chunks",
                doc.source_file,
                metadata.aktenzeichen,
                len(chunks),
            )
        except Exception as e:
            msg = f"Failed to process {doc.source_file}: {e}"
            logger.exception(msg)
            errors.append(msg)

    if not all_chunks:
        return {
            "documents_processed": len(parsed_docs),
            "chunks_created": 0,
            "errors": errors or ["All documents produced zero chunks"],
        }

    # 3. Embed all chunks
    logger.info("Step 3/5: Embedding %d chunks", len(all_chunks))
    embedder = EmbeddingClient(settings)
    texts = [chunk.text for chunk in all_chunks]
    try:
        embeddings = embedder.embed_documents(texts)
    except Exception as e:
        msg = f"Embedding failed: {e}"
        logger.exception(msg)
        return {
            "documents_processed": len(parsed_docs),
            "chunks_created": 0,
            "errors": errors + [msg],
        }

    # 4. Store chunks in Qdrant
    logger.info("Step 4/5: Storing %d chunks in Qdrant", len(all_chunks))
    store = VectorStore(settings)
    store.ensure_collection()
    try:
        points_count = store.upsert_chunks(all_chunks, embeddings)
    except Exception as e:
        msg = f"Qdrant upsert failed: {e}"
        logger.exception(msg)
        return {
            "documents_processed": len(parsed_docs),
            "chunks_created": 0,
            "errors": errors + [msg],
        }

    # 5. Build and store document-level records (embeddings + URLs)
    logger.info("Step 5/5: Building document-level records")
    try:
        _build_doc_records(all_chunks, embeddings, doc_metadata, doc_markdowns, store)
    except Exception as e:
        msg = f"Doc record creation failed: {e}"
        logger.exception(msg)
        errors.append(msg)

    logger.info(
        "Ingestion complete: %d documents, %d chunks, %d errors",
        len(parsed_docs),
        points_count,
        len(errors),
    )

    return {
        "documents_processed": len(parsed_docs),
        "chunks_created": points_count,
        "errors": errors,
    }


def _build_doc_records(
    chunks: list[Chunk],
    embeddings: list[list[float]],
    doc_metadata: dict[str, DocumentMetadata],
    doc_markdowns: dict[str, str],
    store: VectorStore,
) -> None:
    """Compute doc-level mean embeddings, extract URLs, store in doc collection."""
    # Group chunk embeddings by aktenzeichen
    az_embeddings: dict[str, list[list[float]]] = defaultdict(list)
    for chunk, emb in zip(chunks, embeddings):
        az_embeddings[chunk.metadata.aktenzeichen].append(emb)

    records: list[dict] = []
    doc_embeds: list[list[float]] = []

    for az, chunk_embs in az_embeddings.items():
        meta = doc_metadata.get(az)
        if not meta:
            continue

        # Mean embedding across all chunks
        mean_emb = VectorStore.mean_embedding(chunk_embs)

        # Extract external URLs from the document markdown
        markdown = doc_markdowns.get(az, "")
        urls = extract_urls(markdown)
        url_records = [
            {"url": u.url, "label": u.label, "context": u.context} for u in urls
        ]

        records.append({
            "aktenzeichen": meta.aktenzeichen,
            "title": meta.title,
            "fachbereich_number": meta.fachbereich_number,
            "fachbereich": meta.fachbereich,
            "document_type": meta.document_type,
            "completion_date": meta.completion_date,
            "language": meta.language,
            "source_file": meta.source_file,
            "urls": url_records,
        })
        doc_embeds.append(mean_emb)

    if records:
        store.ensure_doc_collection()
        store.upsert_doc_records(records, doc_embeds)
        logger.info("Stored %d document-level records", len(records))
