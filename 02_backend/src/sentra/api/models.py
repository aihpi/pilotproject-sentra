from pydantic import BaseModel

from sentra import domain

# The service layer returns domain dataclasses. Converting them into these
# response models is the edge's job, which is why the from_domain constructors
# live here and not in sentra.services. The mapping is written out field by
# field on purpose: a rename on either side should show up as a type error here
# rather than silently changing the API.


class IngestStartResponse(BaseModel):
    status: str


class IngestionStatusResponse(BaseModel):
    status: str  # idle | running | completed | failed
    total_files: int
    processed: int
    skipped: int
    chunks_created: int
    errors: list[str]
    current_file: str
    started_at: str | None = None
    completed_at: str | None = None


class DocumentInfo(BaseModel):
    aktenzeichen: str
    title: str
    fachbereich_number: str
    fachbereich: str
    document_type: str
    completion_date: str
    language: str
    source_file: str


class FeedbackRequest(BaseModel):
    question: str
    answer: str
    rating: str  # "positive" or "negative"
    comment: str | None = None


class FeedbackResponse(BaseModel):
    status: str


class HealthResponse(BaseModel):
    status: str
    qdrant: str
    collection: dict | None = None


# ── Explorer API models (v2) ────────────────────────────────────────


class DateRange(BaseModel):
    date_from: str | None = None  # "YYYY" year string
    date_to: str | None = None


def date_range_params(
    date_range: DateRange | None,
) -> tuple[str | None, str | None]:
    """Unpack an optional DateRange into the two strings the services take."""
    if date_range is None:
        return None, None
    return date_range.date_from, date_range.date_to


# UC#1 – Documents by topic
class DocumentSearchRequest(BaseModel):
    query: str
    date_range: DateRange | None = None
    fachbereich: str | None = None
    document_type: str | None = None
    top_k: int = 20


class DocumentSearchResult(BaseModel):
    aktenzeichen: str
    title: str
    fachbereich: str
    document_type: str
    completion_date: str
    relevance_score: float
    source_file: str

    @classmethod
    def from_domain(cls, doc: domain.ScoredDocument) -> "DocumentSearchResult":
        return cls(
            aktenzeichen=doc.aktenzeichen,
            title=doc.title,
            fachbereich=doc.fachbereich,
            document_type=doc.document_type,
            completion_date=doc.completion_date,
            relevance_score=doc.relevance_score,
            source_file=doc.source_file,
        )


class DocumentSearchResponse(BaseModel):
    documents: list[DocumentSearchResult]


# UC#4 – Similar documents
class SimilarDocumentsRequest(BaseModel):
    aktenzeichen: str
    top_k: int = 10


# Response reuses DocumentSearchResponse


# UC#6 – External sources
class ExternalSourcesRequest(BaseModel):
    query: str
    date_range: DateRange | None = None
    fachbereich: str | None = None
    document_type: str | None = None


class CitedInDoc(BaseModel):
    aktenzeichen: str
    title: str

    @classmethod
    def from_domain(cls, ref: domain.DocumentRef) -> "CitedInDoc":
        return cls(aktenzeichen=ref.aktenzeichen, title=ref.title)


class ExternalSourceResult(BaseModel):
    url: str
    label: str
    context: str
    cited_in: list[CitedInDoc]

    @classmethod
    def from_domain(cls, source: domain.ExternalSource) -> "ExternalSourceResult":
        return cls(
            url=source.url,
            label=source.label,
            context=source.context,
            cited_in=[CitedInDoc.from_domain(r) for r in source.cited_in],
        )


class ExternalSourcesResponse(BaseModel):
    sources: list[ExternalSourceResult]


# UC#2 + UC#10 – Generated answers
class AnswerRequest(BaseModel):
    query: str
    date_range: DateRange | None = None
    fachbereich: str | None = None
    document_type: str | None = None
    # Omit to use RETRIEVAL_TOP_K. The other endpoints keep literal defaults
    # because they count documents rather than chunks.
    top_k: int | None = None
    system_prompt: str | None = None


class AnswerSourceRef(BaseModel):
    aktenzeichen: str
    title: str
    fachbereich: str
    completion_date: str
    source_file: str

    @classmethod
    def from_domain(cls, ref: domain.SourceRef) -> "AnswerSourceRef":
        return cls(
            aktenzeichen=ref.aktenzeichen,
            title=ref.title,
            fachbereich=ref.fachbereich,
            completion_date=ref.completion_date,
            source_file=ref.source_file,
        )


class GeneratedAnswerResponse(BaseModel):
    text: str
    sources: list[AnswerSourceRef]
    system_prompt: str | None = None
