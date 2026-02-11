from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str
    fachbereich: str | None = None
    document_type: str | None = None
    top_k: int = 10


class SourceResponse(BaseModel):
    aktenzeichen: str
    title: str
    section_title: str
    fachbereich: str
    score: float
    text_preview: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]


class IngestResponse(BaseModel):
    documents_processed: int
    chunks_created: int
    errors: list[str]


class DocumentInfo(BaseModel):
    aktenzeichen: str
    title: str
    fachbereich_number: str
    fachbereich: str
    document_type: str
    completion_date: str
    language: str
    source_file: str


class HealthResponse(BaseModel):
    status: str
    qdrant: str
    collection: dict | None = None
