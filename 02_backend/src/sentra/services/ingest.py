import logging

from sentra.config import Settings
from sentra.ingestion.chunker import Chunk, chunk_document
from sentra.ingestion.metadata import extract_metadata
from sentra.ingestion.parser import parse_pdfs
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.store import VectorStore

logger = logging.getLogger(__name__)


def run_ingestion(settings: Settings) -> dict:
    """Run the full document ingestion pipeline.

    Pipeline: PDF → Docling → metadata extraction → chunking → embedding → Qdrant

    Returns a summary dict with counts and any errors.
    """
    errors: list[str] = []

    # 1. Parse PDFs with Docling
    logger.info("Step 1/4: Parsing PDFs from %s", settings.documents_dir)
    parsed_docs = parse_pdfs(settings.documents_dir)
    if not parsed_docs:
        return {
            "documents_processed": 0,
            "chunks_created": 0,
            "errors": ["No PDF files found or all failed to parse"],
        }

    # 2. Extract metadata and chunk each document
    logger.info("Step 2/4: Extracting metadata and chunking %d documents", len(parsed_docs))
    all_chunks: list[Chunk] = []

    for doc in parsed_docs:
        try:
            metadata = extract_metadata(
                doc.markdown, doc.furniture_text, doc.source_file, doc.pdf_metadata
            )
            chunks = chunk_document(
                doc.markdown, metadata, max_tokens=settings.chunk_max_tokens
            )
            all_chunks.extend(chunks)
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
    logger.info("Step 3/4: Embedding %d chunks", len(all_chunks))
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

    # 4. Store in Qdrant
    logger.info("Step 4/4: Storing %d chunks in Qdrant", len(all_chunks))
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
