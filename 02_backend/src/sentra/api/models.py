from pydantic import BaseModel


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


class ExternalSourceResult(BaseModel):
    url: str
    label: str
    context: str
    cited_in: list[CitedInDoc]


class ExternalSourcesResponse(BaseModel):
    sources: list[ExternalSourceResult]


# UC#2 + UC#10 – Generated answers
class AnswerRequest(BaseModel):
    query: str
    date_range: DateRange | None = None
    fachbereich: str | None = None
    document_type: str | None = None
    top_k: int = 10
    system_prompt: str | None = None


class AnswerSourceRef(BaseModel):
    aktenzeichen: str
    title: str
    fachbereich: str
    completion_date: str
    source_file: str


class GeneratedAnswerResponse(BaseModel):
    text: str
    sources: list[AnswerSourceRef]
    system_prompt: str | None = None
