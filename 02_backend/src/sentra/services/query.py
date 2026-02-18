import logging
from collections.abc import Iterator
from dataclasses import dataclass

from sentra.config import Settings
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.generator import AnswerGenerator, format_context
from sentra.rag.store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class Source:
    """A source reference for a RAG answer."""

    aktenzeichen: str
    title: str
    section_title: str
    fachbereich: str
    score: float
    text_preview: str
    source_file: str


@dataclass
class QueryResult:
    """Result of a RAG query."""

    answer: str
    sources: list[Source]


def run_query(
    question: str,
    settings: Settings,
    fachbereich: str | None = None,
    document_type: str | None = None,
    top_k: int | None = None,
) -> QueryResult:
    """Run the full RAG query pipeline.

    Pipeline: query → embed → search Qdrant → assemble context → generate answer
    """
    k = top_k or settings.retrieval_top_k

    # 1. Embed the query
    embedder = EmbeddingClient(settings)
    query_embedding = embedder.embed_query(question)

    # 2. Search Qdrant
    store = VectorStore(settings)
    results = store.search(
        query_embedding=query_embedding,
        top_k=k,
        fachbereich=fachbereich,
        document_type=document_type,
    )

    if not results:
        return QueryResult(
            answer="Es wurden keine relevanten Dokumente gefunden.",
            sources=[],
        )

    # 3. Deduplicate sources and build source list
    sources = _build_sources(results)

    # 4. Generate answer
    context = format_context(results)
    generator = AnswerGenerator(settings)
    answer = generator.generate(question, context)

    return QueryResult(answer=answer, sources=sources)


def run_query_stream(
    question: str,
    settings: Settings,
    fachbereich: str | None = None,
    document_type: str | None = None,
    top_k: int | None = None,
) -> tuple[Iterator[str], list[Source]]:
    """Run RAG query with streaming answer generation.

    Returns (answer_stream, sources) where answer_stream yields text chunks.
    Sources are returned immediately after retrieval (before generation starts).
    """
    k = top_k or settings.retrieval_top_k

    # 1. Embed the query
    embedder = EmbeddingClient(settings)
    query_embedding = embedder.embed_query(question)

    # 2. Search Qdrant
    store = VectorStore(settings)
    results = store.search(
        query_embedding=query_embedding,
        top_k=k,
        fachbereich=fachbereich,
        document_type=document_type,
    )

    if not results:

        def empty_stream() -> Iterator[str]:
            yield "Es wurden keine relevanten Dokumente gefunden."

        return empty_stream(), []

    # 3. Build sources
    sources = _build_sources(results)

    # 4. Stream answer generation
    context = format_context(results)
    generator = AnswerGenerator(settings)
    stream = generator.generate_stream(question, context)

    return stream, sources


def _build_sources(results: list[dict]) -> list[Source]:
    """Build deduplicated source list from search results."""
    seen: set[str] = set()
    sources: list[Source] = []

    for r in results:
        # Deduplicate by aktenzeichen + section
        key = f"{r['aktenzeichen']}::{r['section_title']}"
        if key in seen:
            continue
        seen.add(key)

        # Take first 200 chars of chunk text as preview, strip the section heading
        text = r.get("text", "")
        # Remove the section title from the start if duplicated
        if text.startswith(r["section_title"]):
            text = text[len(r["section_title"]):].lstrip("\n ")
        preview = text[:200].rstrip()
        if len(text) > 200:
            preview += "..."

        sources.append(
            Source(
                aktenzeichen=r["aktenzeichen"],
                title=r["title"],
                section_title=r["section_title"],
                fachbereich=r["fachbereich"],
                score=r["score"],
                text_preview=preview,
                source_file=r.get("source_file", ""),
            )
        )

    return sources
