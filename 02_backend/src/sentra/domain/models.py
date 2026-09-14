"""Types shared across modules.

This module exists so that shared types have a home that is not "wherever they
were first needed". Everything here is a plain dataclass with no dependency on
FastAPI, pydantic, Qdrant or the AI Hub, which is what lets the layers above
depend downwards only:

    api -> explorer -> {retrieval, generation, ingestion} -> domain -> config

Nothing in here imports from anywhere else in sentra except this package.
"""

from dataclasses import dataclass, field

# ── Documents ───────────────────────────────────────────────────────


@dataclass
class DocumentMetadata:
    """Structured metadata extracted from a Bundestag WD document."""

    aktenzeichen: str
    fachbereich_number: str
    fachbereich: str
    document_type: str
    title: str
    completion_date: str
    language: str
    source_file: str


@dataclass
class Chunk:
    """A text chunk from a Bundestag document, ready for embedding."""

    text: str
    section_title: str
    section_path: str
    chunk_index: int
    metadata: DocumentMetadata


@dataclass
class DocumentRef:
    """The least you need to point at a document."""

    aktenzeichen: str
    title: str


# ── Retrieval ───────────────────────────────────────────────────────


@dataclass
class Hit:
    """One chunk returned by a similarity search, with its score.

    The store still returns dictionaries today. Adopting this type there, and in
    every consumer, is the typed-hit task; it lives here now so that task has
    somewhere to put it and so the shape is agreed in one place first.
    """

    score: float
    text: str
    section_title: str
    section_path: str
    chunk_index: int
    aktenzeichen: str
    fachbereich_number: str
    fachbereich: str
    document_type: str
    title: str
    completion_date: str
    language: str
    source_file: str


@dataclass
class ScoredDocument:
    """A document matching a query, scored by its best chunk."""

    aktenzeichen: str
    title: str
    fachbereich: str
    document_type: str
    completion_date: str
    relevance_score: float
    source_file: str


# ── Answers ─────────────────────────────────────────────────────────


@dataclass
class SourceRef:
    """A document cited by a generated answer."""

    aktenzeichen: str
    title: str
    fachbereich: str
    completion_date: str
    source_file: str


@dataclass
class ExternalSource:
    """An external URL cited by one or more documents."""

    url: str
    label: str
    context: str
    cited_in: list[DocumentRef] = field(default_factory=list)


@dataclass
class AnswerResult:
    """A generated answer together with the sources it drew on."""

    text: str
    sources: list[SourceRef]
    system_prompt: str | None = None
