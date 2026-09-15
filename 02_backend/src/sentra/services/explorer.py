"""Explorer service layer — one function per use case.

UC#1  search_documents_by_topic   chunk search → aggregate to doc list
UC#2  generate_overview           chunk search → LLM structured summary
UC#4  find_similar_documents      doc-level embedding similarity
UC#6  find_external_sources       chunk search → aggregate cited URLs
UC#10 answer_question             chunk search → LLM focused answer
"""

import logging

from sentra.domain import (
    AnswerResult,
    DocumentRef,
    ExternalSource,
    Hit,
    ScoredDocument,
    SourceRef,
)
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.generator import (
    FACHFRAGE_PROMPT,
    OVERVIEW_PROMPT,
    AnswerGenerator,
    AnswerMethod,
    format_context,
)
from sentra.rag.store import VectorStore

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────


def _aggregate_docs(hits: list[Hit], top_k: int) -> list[ScoredDocument]:
    """Aggregate chunk-level hits into unique documents (best score wins)."""
    best: dict[str, Hit] = {}
    for hit in hits:
        current = best.get(hit.aktenzeichen)
        if current is None or hit.score > current.score:
            best[hit.aktenzeichen] = hit

    ranked = sorted(best.values(), key=lambda h: h.score, reverse=True)
    return [
        ScoredDocument(
            aktenzeichen=hit.aktenzeichen,
            title=hit.title,
            fachbereich=hit.fachbereich,
            document_type=hit.document_type,
            completion_date=hit.completion_date,
            relevance_score=round(hit.score, 4),
            source_file=hit.source_file,
        )
        for hit in ranked[:top_k]
    ]


def _build_source_refs(hits: list[Hit]) -> list[SourceRef]:
    """Deduplicate hits into source references, ordered by first appearance.

    The order matters: the prompts tell the model that [n] refers to the nth
    source in order of first appearance, so this is what the numbering in a
    generated answer is supposed to line up with.
    """
    seen: set[str] = set()
    refs: list[SourceRef] = []
    for hit in hits:
        if hit.aktenzeichen in seen:
            continue
        seen.add(hit.aktenzeichen)
        refs.append(
            SourceRef(
                aktenzeichen=hit.aktenzeichen,
                title=hit.title,
                fachbereich=hit.fachbereich,
                completion_date=hit.completion_date,
                source_file=hit.source_file,
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
) -> list[ScoredDocument]:
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
) -> list[ScoredDocument]:
    """Find documents similar to the given Aktenzeichen.

    Uses the document-level embedding collection.
    """
    results = store.search_similar_docs(aktenzeichen, top_k=top_k)

    return [
        ScoredDocument(
            aktenzeichen=scored.record.metadata.aktenzeichen,
            title=scored.record.metadata.title,
            fachbereich=scored.record.metadata.fachbereich,
            document_type=scored.record.metadata.document_type,
            completion_date=scored.record.metadata.completion_date,
            relevance_score=round(scored.score, 4),
            source_file=scored.record.metadata.source_file,
        )
        for scored in results
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
) -> list[ExternalSource]:
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
    for hit in results:
        if hit.aktenzeichen not in az_set:
            az_set[hit.aktenzeichen] = hit.title

    # Look up doc records to get URLs
    doc_records = store.get_doc_records_by_aktenzeichen(list(az_set.keys()))

    # Aggregate URLs across documents
    url_map: dict[str, ExternalSource] = {}
    for doc in doc_records:
        az = doc.metadata.aktenzeichen
        title = doc.metadata.title or az_set.get(az, "")
        for u in doc.urls:
            url = u.url
            if url in url_map:
                existing_az = {c.aktenzeichen for c in url_map[url].cited_in}
                if az not in existing_az:
                    url_map[url].cited_in.append(DocumentRef(aktenzeichen=az, title=title))
            else:
                url_map[url] = ExternalSource(
                    url=url,
                    label=u.label,
                    context=u.context,
                    cited_in=[DocumentRef(aktenzeichen=az, title=title)],
                )

    # Sort by number of citing documents (descending)
    return sorted(url_map.values(), key=lambda s: len(s.cited_in), reverse=True)


# ── Answer / Overview generation (shared logic) ─────────────────────


def _generate(
    query: str,
    date_from: str | None,
    date_to: str | None,
    top_k: int,
    store: VectorStore,
    embedder: EmbeddingClient,
    generate: AnswerMethod,
    default_prompt: str,
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
    text = generate(query, context, system_prompt=system_prompt)

    return AnswerResult(text=text, sources=sources, system_prompt=effective_prompt)


# ── UC#10: Answer question ──────────────────────────────────────────


def answer_question(
    query: str,
    date_from: str | None,
    date_to: str | None,
    top_k: int,
    store: VectorStore,
    embedder: EmbeddingClient,
    generator: AnswerGenerator,
    fachbereich: str | None = None,
    document_type: str | None = None,
    system_prompt: str | None = None,
) -> AnswerResult:
    """Answer a specific Fachfrage with source citations."""
    return _generate(
        query,
        date_from,
        date_to,
        top_k,
        store,
        embedder,
        generator.generate_answer,
        FACHFRAGE_PROMPT,
        fachbereich,
        document_type,
        system_prompt,
    )


# ── UC#2: Topic overview ────────────────────────────────────────────


def generate_overview(
    query: str,
    date_from: str | None,
    date_to: str | None,
    top_k: int,
    store: VectorStore,
    embedder: EmbeddingClient,
    generator: AnswerGenerator,
    fachbereich: str | None = None,
    document_type: str | None = None,
    system_prompt: str | None = None,
) -> AnswerResult:
    """Generate a structured topic overview."""
    return _generate(
        query,
        date_from,
        date_to,
        top_k,
        store,
        embedder,
        generator.generate_overview,
        OVERVIEW_PROMPT,
        fachbereich,
        document_type,
        system_prompt,
    )
