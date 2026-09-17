"""Request and response models for the eval API.

Here rather than in sentra.api.models, and an import-linter contract keeps them
here. The harness has its own audience and its own vocabulary — the field names
below are the Vorlage's, in German, because a Phase-4 documentation sheet is
filled in from them and translating twice is how two vocabularies drift apart.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from sentra_eval.categories import Kategorie


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
    referenz_korrekt_az: str
    referenz_falsch_az: str
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
    # The Aktenzeichen the mechanical check matches on. The two fields above
    # hold the citation a reviewer reads; these hold what SENTRA actually cites.
    referenz_korrekt_az: str = ""
    referenz_falsch_az: str = ""
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
    referenz_korrekt_az: str | None = None
    referenz_falsch_az: str | None = None
    grund_fuer_aufnahme: str | None = None
    grenzfall: bool | None = None


class StartRunRequest(BaseModel):
    label: str = ""
    # 4.1 asks for three. Configurable because a smoke run of one is useful and
    # a round of three is what the Vorlage specifies.
    repeats: int = Field(default=3, ge=1, le=10)
    # Stufe 3's rate. The Vorlage leaves it open and suggests 10 percent as a
    # starting point; it is stored on the run, so changing it later cannot
    # change what a finished round did.
    stichprobe_anteil: float = Field(default=0.1, ge=0.0, le=1.0)
    # Fixed explicitly only to reproduce a round. Otherwise drawn once and kept.
    stichprobe_seed: int | None = None


class RunResponse(BaseModel):
    id: UUID
    label: str
    status: str
    sentra_base_url: str
    repeats: int
    started_at: datetime
    completed_at: datetime | None
    fehler: str
    stichprobe_seed: int
    stichprobe_anteil: float
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
    zweck: str
    request_body: dict
    response_body: dict
    checks: list["CheckResultResponse"] = []


class CheckResultResponse(BaseModel):
    pruefung: str
    ergebnis: str
    auffaellig: bool
    belege: dict


class QueueCall(BaseModel):
    """One answer awaiting assessment.

    No check results here, and that omission is the design. See review.py.
    """

    id: UUID
    variant_key: str
    repeat_index: int
    text: str
    sources: list[dict]
    http_status: int | None
    dauer_ms: float | None


class QueueEntryResponse(BaseModel):
    test_id: str
    kategorie: str
    case_version_id: UUID
    version: int
    # The yardstick, read only. It is what the answer is measured against, so a
    # review screen shows it beside the answer and never lets it be edited
    # while somebody is looking at a disappointing result.
    ausgangsfrage: str
    erwartete_antwort: str
    referenz_korrekt: str
    referenz_falsch: str
    grenzfall: bool
    gefunden_ueber: str
    calls: list[QueueCall]
    # One sheet per case, so this is a fact about the case rather than a count
    # of how many of its answers somebody got through.
    assessed: bool


class MachineVerdictsResponse(BaseModel):
    """Served by its own endpoint, after the human has submitted."""

    per_call: list[CheckResultResponse]
    per_group: list[CheckResultResponse]


class SubmitVerdictRequest(BaseModel):
    """One sheet, per section 6 of the Vorlage: Dokumentation je Testfall."""

    # No authentication exists anywhere in this project, so this is typed. It
    # is required because a finding nobody has to own is a finding nobody
    # follows up.
    tester: str = Field(min_length=1)
    # "Kernbefund je Variante", keyed "<variant_key>#<repeat_index>". One field
    # on the sheet, one field here.
    kernbefunde: dict[str, str] = Field(default_factory=dict)
    # gefunden_ueber is deliberately absent: the server derives it. It says how
    # the case reached a reviewer, which is half of what the trend report
    # measures, and a client asserting it could misattribute a finding.
    quelle_4_3a: str
    quelle_4_3b: str
    # Never prefilled from a check. Whether a source actually supports a claim
    # is the fachliche Einschätzung the Vorlage keeps in human hands.
    quelle_4_3c: str
    schweregrad: int = Field(ge=1, le=4)
    reproduzierbar: str
    anmerkung: str = ""


class VerdictResponse(BaseModel):
    id: UUID
    run_id: UUID
    case_version_id: UUID
    tester: str
    kernbefunde: dict[str, str]
    gefunden_ueber: str
    quelle_4_3a: str
    quelle_4_3b: str
    quelle_4_3c: str
    schweregrad: int
    reproduzierbar: str
    anmerkung: str
    kisz_meldung: bool
    created_at: datetime


class VorlageOptions(BaseModel):
    """The Phase-4 sheet's closed lists, for the review form's dropdowns.

    Served rather than duplicated in the frontend, for the reason #37 gave
    about prompts and filters: two copies of a vocabulary drift, and this one
    has to match a paper form.
    """

    quelle_4_3a: list[str]
    quelle_4_3b: list[str]
    quelle_4_3c: list[str]
    reproduzierbar: list[str]
    gefunden_ueber: list[str]
    schweregrad: dict[int, str]


class TriageSummary(BaseModel):
    """What Stufe 1 decided, in aggregate.

    Worth being able to see at a glance: a round where everything is flagged
    means the threshold is filtering nothing, and a round where nothing is
    means it may be filtering too much. That ratio is the thing being
    calibrated.
    """

    gesamt: int
    stufe_2: int
    stufe_3: int
    grenzfaelle: int
    unauffaellig: int


class SheetResponse(BaseModel):
    """One Phase-4 documentation sheet, section 6 of the Vorlage, field for field.

    German field names on purpose: this is what goes to KISZ, and a sheet whose
    labels have to be translated back before anyone can read it is a sheet
    somebody will retype.
    """

    test_id: str
    datum: str
    tester: str
    kategorie: str
    angewendete_techniken: list[str]
    urspruenglicher_prompt: str
    geprüfte_varianten: list[str]
    varianten_erstellt_durch: str
    varianten_freigegeben_durch: str
    automatisiert_geprueft_durch: str
    ergebnis_automatikpruefung: str
    gefunden_ueber: str
    manuell_geprueft_durch: str
    kernbefund_je_variante: dict[str, str]
    quellenbewertung_4_3a: str
    quellenbewertung_4_3b: str
    quellenbewertung_4_3c: str
    schweregrad: int | None
    reproduzierbar: str
    freitext_anmerkung: str


class AgreementResponse(BaseModel):
    """The headline number, and the three counts it comes from.

    `zu_streng` and `zu_grosszuegig` calibrate in opposite directions, so the
    quote alone is not enough to act on — the split is what says which way to
    move the threshold.
    """

    einig: int
    zu_streng: int
    zu_grosszuegig: int
    nicht_bewertet: int
    # None, not 0.0, when nothing has been assessed. A round with no verdicts
    # has no disagreement rate, and reporting zero would read as perfect
    # agreement about a threshold nobody has checked.
    abweichungsquote: float | None


class TrendResponse(BaseModel):
    runden: int
    faelle: int
    nach_kategorie: dict[str, int]
    schweregrade: dict[int, int]
    kisz_meldungen: int
    haeufigste_befunde: dict[str, int]
    abweichung: AgreementResponse


class VariantResponse(BaseModel):
    stil: str
    wortlaut: str
    status: str
    erstellt_durch: str
    freigegeben_durch: str
    freigegeben_at: datetime | None


class EditVariantRequest(BaseModel):
    """Correcting a proposal before approving it.

    A reviewer who can only accept or reject rejects three good variants over
    one clumsy word.
    """

    wortlaut: str = Field(min_length=1)


class ApproveVariantRequest(BaseModel):
    # "Varianten freigegeben durch" on the Phase-4 sheet. Required for the
    # same reason a verdict needs a tester: an approval nobody owns is one
    # nobody can be asked about.
    freigegeben_durch: str = Field(min_length=1)
