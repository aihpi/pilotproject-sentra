"""Explorer service layer — one function per use case.

UC#1  search_documents_by_topic   chunk search → aggregate to doc list
UC#2  generate_overview           chunk search → LLM structured summary
UC#4  find_similar_documents      doc-level embedding similarity
UC#6  find_external_sources       chunk search → aggregate cited URLs
UC#10 answer_question             chunk search → LLM focused answer
"""

import logging
from dataclasses import dataclass

from sentra.api.models import (
    AnswerSourceRef,
    CitedInDoc,
    DateRange,
    DocumentSearchResult,
    ExternalSourceResult,
)
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.generator import (
    FACHFRAGE_PROMPT,
    OVERVIEW_PROMPT,
    AnswerGenerator,
    format_context,
)
from sentra.rag.store import VectorStore

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────


def _date_range_params(
    date_range: DateRange | None,
) -> tuple[str | None, str | None]:
    """Unpack a DateRange model into (date_from, date_to) strings."""
    if date_range is None:
        return None, None
    return date_range.date_from, date_range.date_to


def _aggregate_docs(results: list[dict], top_k: int) -> list[DocumentSearchResult]:
    """Aggregate chunk-level results into unique documents (best score wins)."""
    best: dict[str, dict] = {}
    for r in results:
        az = r["aktenzeichen"]
        if az not in best or r["score"] > best[az]["score"]:
            best[az] = r

    sorted_docs = sorted(best.values(), key=lambda d: d["score"], reverse=True)
    return [
        DocumentSearchResult(
            aktenzeichen=d["aktenzeichen"],
            title=d["title"],
            fachbereich=d["fachbereich"],
            document_type=d.get("document_type", ""),
            completion_date=d.get("completion_date", ""),
            relevance_score=round(d["score"], 4),
            source_file=d.get("source_file", ""),
        )
        for d in sorted_docs[:top_k]
    ]


def _build_source_refs(results: list[dict]) -> list[AnswerSourceRef]:
    """Build deduplicated source references from search results (ordered by first appearance)."""
    seen: set[str] = set()
    refs: list[AnswerSourceRef] = []
    for r in results:
        az = r["aktenzeichen"]
        if az in seen:
            continue
        seen.add(az)
        refs.append(
            AnswerSourceRef(
                aktenzeichen=az,
                title=r["title"],
                fachbereich=r["fachbereich"],
                completion_date=r.get("completion_date", ""),
                source_file=r.get("source_file", ""),
            )
        )
    return refs


# ── UC#1: Documents by topic ────────────────────────────────────────


def search_documents_by_topic(
    query: str,
    date_from: str | None,
    date_to: str | None,
    top_k: int,
    store: VectorStore,
    embedder: EmbeddingClient,
    fachbereich: str | None = None,
    document_type: str | None = None,
) -> list[DocumentSearchResult]:
    """Find documents matching a topic query.

    Searches at chunk level (3x top_k for coverage) then aggregates
    to unique documents by highest chunk score.
    """
    query_embedding = embedder.embed_query(query)
    results = store.search(
        query_embedding=query_embedding,
        top_k=top_k * 3,
        date_from=date_from,
        date_to=date_to,
        fachbereich=fachbereich,
        document_type=document_type,
    )

    return _aggregate_docs(results, top_k)


# ── UC#4: Similar documents ─────────────────────────────────────────


def find_similar_documents(
    aktenzeichen: str,
    top_k: int,
    store: VectorStore,
) -> list[DocumentSearchResult]:
    """Find documents similar to the given Aktenzeichen.

    Uses the document-level embedding collection.
    """
    results = store.search_similar_docs(aktenzeichen, top_k=top_k)

    return [
        DocumentSearchResult(
            aktenzeichen=d["aktenzeichen"],
            title=d["title"],
            fachbereich=d["fachbereich"],
            document_type=d.get("document_type", ""),
            completion_date=d.get("completion_date", ""),
            relevance_score=round(d["score"], 4),
            source_file=d.get("source_file", ""),
        )
        for d in results
    ]


# ── UC#6: External sources ──────────────────────────────────────────


def find_external_sources(
    query: str,
    date_from: str | None,
    date_to: str | None,
    store: VectorStore,
    embedder: EmbeddingClient,
    fachbereich: str | None = None,
    document_type: str | None = None,
) -> list[ExternalSourceResult]:
    """Find external URLs cited in documents matching a topic query.

    Flow: chunk search → get matching Aktenzeichen → look up URLs from
    doc collection → aggregate and deduplicate.
    """
    query_embedding = embedder.embed_query(query)
    results = store.search(
        query_embedding=query_embedding,
        top_k=30,
        date_from=date_from,
        date_to=date_to,
        fachbereich=fachbereich,
        document_type=document_type,
    )

    if not results:
        return []

    # Collect unique Aktenzeichen with their titles
    az_set: dict[str, str] = {}
    for r in results:
        az = r["aktenzeichen"]
        if az not in az_set:
            az_set[az] = r["title"]

    # Look up doc records to get URLs
    doc_records = store.get_doc_records_by_aktenzeichen(list(az_set.keys()))

    # Aggregate URLs across documents
    url_map: dict[str, ExternalSourceResult] = {}
    for doc in doc_records:
        az = doc["aktenzeichen"]
        title = doc.get("title", az_set.get(az, ""))
        for u in doc.get("urls", []):
            url = u["url"]
            if url in url_map:
                existing_az = {c.aktenzeichen for c in url_map[url].cited_in}
                if az not in existing_az:
                    url_map[url].cited_in.append(
                        CitedInDoc(aktenzeichen=az, title=title)
                    )
            else:
                url_map[url] = ExternalSourceResult(
                    url=url,
                    label=u.get("label", ""),
                    context=u.get("context", ""),
                    cited_in=[CitedInDoc(aktenzeichen=az, title=title)],
                )

    # Sort by number of citing documents (descending)
    return sorted(url_map.values(), key=lambda s: len(s.cited_in), reverse=True)


# ── Answer / Overview generation (shared logic) ─────────────────────


@dataclass
class AnswerResult:
    text: str
    sources: list[AnswerSourceRef]
    system_prompt: str | None = None


def _generate(
    query: str,
    date_from: str | None,
    date_to: str | None,
    top_k: int,
    store: VectorStore,
    embedder: EmbeddingClient,
    generator: AnswerGenerator,
    default_prompt: str,
    generator_method: str,
    fachbereich: str | None = None,
    document_type: str | None = None,
    system_prompt: str | None = None,
) -> AnswerResult:
    query_embedding = embedder.embed_query(query)

    effective_prompt = system_prompt or default_prompt

    results = store.search(
        query_embedding=query_embedding,
        top_k=top_k,
        date_from=date_from,
        date_to=date_to,
        fachbereich=fachbereich,
        document_type=document_type,
    )

    if not results:
        return AnswerResult(
            text="Es wurden keine relevanten Dokumente gefunden.",
            sources=[],
            system_prompt=effective_prompt,
        )

    sources = _build_source_refs(results)
    context = format_context(results)
    text = getattr(generator, generator_method)(query, context, system_prompt=system_prompt)

    return AnswerResult(text=text, sources=sources, system_prompt=effective_prompt)


# ── UC#10: Answer question ──────────────────────────────────────────


def answer_question(
    query: str, date_from: str | None, date_to: str | None, top_k: int,
    store: VectorStore, embedder: EmbeddingClient, generator: AnswerGenerator,
    fachbereich: str | None = None,
    document_type: str | None = None, system_prompt: str | None = None,
) -> AnswerResult:
    """Answer a specific Fachfrage with source citations."""
    return _generate(
        query, date_from, date_to, top_k, store, embedder, generator,
        FACHFRAGE_PROMPT, "generate_answer", fachbereich, document_type, system_prompt,
    )


# ── UC#2: Topic overview ────────────────────────────────────────────


def generate_overview(
    query: str, date_from: str | None, date_to: str | None, top_k: int,
    store: VectorStore, embedder: EmbeddingClient, generator: AnswerGenerator,
    fachbereich: str | None = None,
    document_type: str | None = None, system_prompt: str | None = None,
) -> AnswerResult:
    """Generate a structured topic overview."""
    return _generate(
        query, date_from, date_to, top_k, store, embedder, generator,
        OVERVIEW_PROMPT, "generate_overview", fachbereich, document_type, system_prompt,
    )
