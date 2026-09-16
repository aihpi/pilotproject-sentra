"""Request and response models for the eval API.

Here rather than in sentra.api.models, and an import-linter contract keeps them
here. The harness has its own audience and its own vocabulary — the field names
below are the Vorlage's, in German, because a Phase-4 documentation sheet is
filled in from them and translating twice is how two vocabularies drift apart.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from sentra.evaluation.categories import Kategorie


class EvalHealthResponse(BaseModel):
    status: str
    judge_model: str
    sentra_base_url: str
    database: str
    schema_revision: str | None = None


class CaseVersionResponse(BaseModel):
    version: int
    status: str
    ausgangsfrage: str
    abteilung: str
    erwartete_antwort: str
    referenz_korrekt: str
    referenz_falsch: str
    grund_fuer_aufnahme: str
    grenzfall: bool
    created_at: datetime
    freigegeben_at: datetime | None


class CaseResponse(BaseModel):
    test_id: str
    kategorie: str
    created_at: datetime
    zurueckgezogen_at: datetime | None
    versions: list[CaseVersionResponse]


class CreateCaseRequest(BaseModel):
    kategorie: Kategorie
    # The only field a draft must have. Everything else can be filled in later,
    # which is what lets a case be started from a feedback entry or a YAML stub.
    ausgangsfrage: str = Field(min_length=1)
    abteilung: str = ""
    erwartete_antwort: str = ""
    referenz_korrekt: str = ""
    referenz_falsch: str = ""
    grund_fuer_aufnahme: str = ""
    grenzfall: bool = False


class UpdateCaseRequest(BaseModel):
    """Fields to change. Omitted ones are carried over unchanged.

    Against a draft this edits in place. Against an approved version it is
    refused — add a version instead.
    """

    ausgangsfrage: str | None = None
    abteilung: str | None = None
    erwartete_antwort: str | None = None
    referenz_korrekt: str | None = None
    referenz_falsch: str | None = None
    grund_fuer_aufnahme: str | None = None
    grenzfall: bool | None = None


class StartRunRequest(BaseModel):
    label: str = ""
    # 4.1 asks for three. Configurable because a smoke run of one is useful and
    # a round of three is what the Vorlage specifies.
    repeats: int = Field(default=3, ge=1, le=10)


class RunResponse(BaseModel):
    id: UUID
    label: str
    status: str
    sentra_base_url: str
    repeats: int
    started_at: datetime
    completed_at: datetime | None
    fehler: str
    # Progress, so a caller polling this can see a round move.
    total: int
    done: int
    failed: int
    # Whether every version used was approved before the round began. False
    # means the round measured against an expectation that could have been
    # written to fit the answers.
    audit_ok: bool


class CallResponse(BaseModel):
    id: UUID
    test_id: str
    variant_key: str
    repeat_index: int
    status: str
    endpoint: str
    http_status: int | None
    dauer_ms: float | None
    fehler: str
    request_body: dict
    response_body: dict
