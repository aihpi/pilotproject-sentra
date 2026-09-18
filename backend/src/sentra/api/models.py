import re

from pydantic import BaseModel, Field, field_validator

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
    # Documents indexed in Qdrant with no matching file on disk. Computed on
    # every run and previously only logged, so nobody outside the server ever
    # saw the drift it detects.
    stale_documents: list[str] = []


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


class FeedbackEntry(BaseModel):
    """One recorded rating, as stored in feedback.jsonl.

    Served because the evaluation harness needs it: the Vorlage asks for known
    problem cases from earlier feedback to be taken into a round deliberately,
    and the harness is a separate process with no access to this file.

    The id is derived rather than stored. The file is append-only lines written
    since #16 with no identifier, and giving it one retroactively would mean
    rewriting a log in place — the more expensive of the two changes. A uuid5
    over timestamp and question is stable for lines already written.
    """

    id: str
    timestamp: str
    question: str
    answer: str
    rating: str
    comment: str | None = None


class LoginRequest(BaseModel):
    benutzername: str = Field(min_length=1)
    passwort: str = Field(min_length=1)


class MeResponse(BaseModel):
    """The authenticated caller. Deliberately small — a name and a role.

    Nothing else belongs here: every field this grows is a field the frontend
    starts depending on, and the whole point is that swapping the prototype for
    an IdP changes this endpoint and nothing above it.
    """

    benutzername: str
    rolle: str


class UserResponse(BaseModel):
    """A user, without anything secret about them.

    No password and no hash, on any endpoint, ever. The column exists for the
    verifier and nothing else may read it.
    """

    benutzername: str
    rolle: str
    quelle: str = "Datenbank"


class CreateUserRequest(BaseModel):
    benutzername: str = Field(min_length=1)
    rolle: str
    passwort: str = Field(min_length=1)


class UpdateUserRequest(BaseModel):
    """Omitted fields are left alone, so a role change need not resend a
    password and a password reset need not restate the role."""

    rolle: str | None = None
    passwort: str | None = Field(default=None, min_length=1)


class HealthResponse(BaseModel):
    status: str
    qdrant: str
    collection: dict | None = None
    # Whether POST /api/ingest and GET /api/feedback are guarded: "token" or
    # "offen". Reported rather than left to a log line, because a service that
    # answers "healthy" while its write path is open is answering the wrong
    # question. See api/auth.py.
    auth: str = "offen"
    # Whether a login is configured at all. Distinct from `auth`: the token
    # guards two endpoints, this says whether anybody can identify themselves.
    login: str = "nicht eingerichtet"


# ── Explorer API models (v2) ────────────────────────────────────────


# A year as the API accepts it: four digits, not starting with a zero. There is
# deliberately no upper bound. Which years exist is a property of the corpus,
# and a ceiling written here would be wrong the first time somebody ingests a
# document from outside whatever range we guessed.
_YEAR = re.compile(r"[1-9]\d{3}")

# German, like every other message a caller can end up reading.
YEAR_EXPECTED = 'Jahresangabe muss vierstellig sein, zum Beispiel "2023".'


class DateRange(BaseModel):
    """An inclusive year range. Both bounds are "YYYY" strings.

    Both fields used to be plain strings with no validation, so anything at all
    reached rag/store.py, which parsed the year inside a try whose handler
    logged a warning and fell through. The date condition was then never added
    to the query: the search ran across every year in the corpus and answered
    200, with nothing in the response saying the filter had been ignored. A
    mistyped year returned confident results from the wrong period.

    Rejecting here is what keeps that from being reachable. The explorer UI
    could never trigger it — FilterBar renders a year dropdown — so it was
    always a problem for callers using the API directly.
    """

    date_from: str | None = None
    date_to: str | None = None

    @field_validator("date_from", "date_to")
    @classmethod
    def _valid_year(cls, value: str | None) -> str | None:
        # An empty string has always meant "no bound", here and in the store,
        # so it keeps meaning that. Anything else that is not a year is a
        # mistake rather than an absent filter, and is worth failing over.
        if not value:
            return None
        if not _YEAR.fullmatch(value):
            raise ValueError(YEAR_EXPECTED)
        return value


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
    # Opt in to the retrieved context, the finish reason and the model the hub
    # served. Off by default and deliberately so: the chunks are large and the
    # explorer UI has no use for them. The evaluation harness is the caller
    # this exists for.
    debug: bool = False


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


class RetrievedChunk(BaseModel):
    """One chunk the answer was generated from.

    Only present when the request asked for it. This is the whole universe the
    model saw for this source, which is what lets a check ask whether a claim
    is in the context at all rather than inferring it from the answer.
    """

    aktenzeichen: str
    section_title: str
    chunk_index: int
    score: float
    text: str

    @classmethod
    def from_domain(cls, hit: domain.Hit) -> "RetrievedChunk":
        return cls(
            aktenzeichen=hit.aktenzeichen,
            section_title=hit.section_title,
            chunk_index=hit.chunk_index,
            score=hit.score,
            text=hit.text,
        )


class GeneratedAnswerResponse(BaseModel):
    text: str
    sources: list[AnswerSourceRef]
    system_prompt: str | None = None

    # All three are absent unless the request set debug. Without it this model
    # serialises exactly as it did before, which is what keeps the frontend and
    # every existing caller untouched.
    hits: list[RetrievedChunk] | None = None
    # "stop" if the model finished, "length" if it hit the ceiling — 2048 for a
    # Fachfrage, 3072 for an Überblick. A truncated answer looks like an
    # inconsistent one unless you can see this.
    finish_reason: str | None = None
    # What the hub actually ran, which is not necessarily the name we sent.
    model: str | None = None


# ── Client configuration ────────────────────────────────────────────


class ReferatOption(BaseModel):
    """One Referat the UI can filter by.

    The number is the value to filter on, because fachbereich_number is the
    indexed field. The name is a label only, and it comes from the mapping in
    the extractor rather than from the documents: the names the documents carry
    are inconsistent (14 spellings for WD 2 alone, and WD 5 and WD 8 were both
    reorganised at some point), so they cannot label a dropdown.
    """

    number: str
    name: str


class ConfigResponse(BaseModel):
    """Everything the UI needs at start-up and used to hardcode.

    One endpoint rather than three, because the client needs all of it on
    mount and never one part without the others.
    """

    prompts: dict[str, str]
    document_types: list[str]
    referate: list[ReferatOption]
