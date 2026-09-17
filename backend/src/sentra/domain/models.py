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
class ExternalUrl:
    """An external URL found in a document, with the text around it."""

    url: str
    label: str
    context: str


@dataclass
class DocumentRecord:
    """One document in the doc-summary collection: its metadata and its links."""

    metadata: DocumentMetadata
    urls: list[ExternalUrl] = field(default_factory=list)


@dataclass
class ScoredDocumentRecord:
    """A document record returned by a similarity search."""

    score: float
    record: DocumentRecord


@dataclass
class DocumentRef:
    """The least you need to point at a document."""

    aktenzeichen: str
    title: str


# ── Retrieval ───────────────────────────────────────────────────────


@dataclass
class Hit:
    """One chunk returned by a similarity search, with its score.

    Flat rather than nesting the document metadata, because every consumer reads
    a mix of chunk fields and document fields and the extra hop buys nothing.
    The store is the only place that builds these, in `_hit_from_point`, so the
    question of which payload fields may be absent is answered once there.
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
class Generation:
    """What one call to the chat model produced.

    finish_reason and model used to be discarded. Both matter to anything
    judging the answer: "length" means the model was cut off at a ceiling
    rather than finishing, which reads as an inconsistency if you only see the
    text; and the model name we send is not a guarantee of what answered.
    """

    text: str
    finish_reason: str | None = None
    model: str | None = None


@dataclass
class AnswerResult:
    """A generated answer together with the sources it drew on."""

    text: str
    sources: list[SourceRef]
    system_prompt: str | None = None
    # Only populated when the caller asked for it. The chunks are large and the
    # explorer UI has no use for them, so the default response does not carry
    # them — but without them nothing can check whether a claim is in the
    # context at all.
    hits: list[Hit] = field(default_factory=list)
    finish_reason: str | None = None
    model: str | None = None
