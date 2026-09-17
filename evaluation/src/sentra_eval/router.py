"""The harness's own API surface, mounted at /api/eval.

Its response models live here rather than in sentra.api.models, and an
import-linter contract keeps them there. The harness is a separate concern with
a separate audience — Hotline and WD working through a round, not somebody
searching documents — and letting the two share models is how services/explorer.py
ended up importing from the API layer.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from sentra_eval import cases as case_store
from sentra_eval import models, triage
from sentra_eval import report as report_store
from sentra_eval import review as review_store
from sentra_eval import runner as run_store
from sentra_eval import variants as variant_store
from sentra_eval.categories import KATEGORIE_NAMEN
from sentra_eval.config import EvalSettings, get_eval_settings
from sentra_eval.db import EvalDatabaseUnavailable, schema_revision, session_scope
from sentra_eval.jobs import BackgroundJob
from sentra_eval.judge import JudgeUnavailable, judge_config
from sentra_eval.models import (
    LAUFEND,
    Call,
    Case,
    CaseVersion,
    CheckResult,
    GroupCheckResult,
    Run,
    Verdict,
)
from sentra_eval.schemas import (
    AgreementResponse,
    ApproveVariantRequest,
    CallResponse,
    CaseResponse,
    CaseVersionResponse,
    CheckResultResponse,
    CreateCaseRequest,
    EditVariantRequest,
    EvalHealthResponse,
    MachineVerdictsResponse,
    QueueCall,
    QueueEntryResponse,
    RunResponse,
    SheetResponse,
    StartRunRequest,
    SubmitVerdictRequest,
    TrendResponse,
    TriageSummary,
    UpdateCaseRequest,
    VariantResponse,
    VerdictResponse,
    VorlageOptions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eval", tags=["evaluation"])

# One round at a time, per process. A second round against the same SENTRA
# would double the hub spend and interleave two sets of answers in the same
# collection of rows. BackgroundJob is #81's, extracted so the harness could
# reuse ingestion's hard-won check-and-start-under-one-lock.
_EVAL_JOB = BackgroundJob("eval-run")


@router.get("/health", response_model=EvalHealthResponse)
def health(settings: EvalSettings = Depends(get_eval_settings)) -> EvalHealthResponse:
    """Whether the harness is mounted, and what it is pointed at.

    Reaching this at all is the answer to the first question: the router is
    only mounted when EVAL_ENABLED is set. The two values say which judge the
    verdicts will come from and which SENTRA the runner will call, both of
    which are worth being able to read off a running instance rather than
    inferring from a deployment.

    The API key is deliberately not here.

    This is the one eval route that answers while the database is down, and
    deliberately so: "is the harness mounted" and "is its database reachable"
    are different questions, and an endpoint that 503s when the answer to the
    second is no cannot tell you which one you are looking at. Every other eval
    route needs the database and gets the 503.
    """
    database, revision = _database_state()
    return EvalHealthResponse(
        status="ok",
        judge_model=judge_config().model,
        sentra_base_url=settings.sentra_base_url,
        database=database,
        schema_revision=revision,
    )


def _database_state() -> tuple[str, str | None]:
    """Whether the database answers, and at which revision.

    A database that is up but has never been migrated is "connected" with no
    revision, which is a real state worth being able to see: it is what a fresh
    deployment looks like before anybody ran `alembic upgrade head`.
    """
    try:
        return "connected", schema_revision()
    except EvalDatabaseUnavailable as exc:
        logger.warning("Eval database unavailable: %s", exc)
        return "unavailable", None
    except Exception as exc:  # noqa: BLE001 — health never raises, it reports
        logger.warning("Eval database in an unexpected state: %s", exc)
        return "error", None


# ── Test cases (Phase 1 of the Vorlage) ─────────────────────────────


def _as_response(case: Case) -> CaseResponse:
    return CaseResponse(
        test_id=case.test_id,
        kategorie=case.kategorie,
        created_at=case.created_at,
        zurueckgezogen_at=case.zurueckgezogen_at,
        versions=[
            CaseVersionResponse(
                version=v.version,
                status=v.status,
                ausgangsfrage=v.ausgangsfrage,
                abteilung=v.abteilung,
                erwartete_antwort=v.erwartete_antwort,
                referenz_korrekt=v.referenz_korrekt,
                referenz_falsch=v.referenz_falsch,
                referenz_korrekt_az=v.referenz_korrekt_az,
                referenz_falsch_az=v.referenz_falsch_az,
                grund_fuer_aufnahme=v.grund_fuer_aufnahme,
                grenzfall=v.grenzfall,
                created_at=v.created_at,
                freigegeben_at=v.freigegeben_at,
            )
            for v in case.versions
        ],
    )


@router.get("/cases", response_model=list[CaseResponse])
def list_cases(include_withdrawn: bool = False) -> list[CaseResponse]:
    """Every case, newest version last within each."""
    with session_scope() as session:
        return [
            _as_response(c)
            for c in case_store.list_cases(session, include_withdrawn=include_withdrawn)
        ]


@router.post("/cases", response_model=CaseResponse, status_code=201)
def create_case(body: CreateCaseRequest) -> CaseResponse:
    """A new case. The Test-ID is allocated here and never reused."""
    with session_scope() as session:
        case, _ = case_store.create_case(
            session,
            kategorie=body.kategorie,
            ausgangsfrage=body.ausgangsfrage,
            abteilung=body.abteilung,
            erwartete_antwort=body.erwartete_antwort,
            referenz_korrekt=body.referenz_korrekt,
            referenz_falsch=body.referenz_falsch,
            referenz_korrekt_az=body.referenz_korrekt_az,
            referenz_falsch_az=body.referenz_falsch_az,
            grund_fuer_aufnahme=body.grund_fuer_aufnahme,
            grenzfall=body.grenzfall,
        )
        return _as_response(case)


@router.get("/cases/{test_id}", response_model=CaseResponse)
def get_case(test_id: str) -> CaseResponse:
    with session_scope() as session:
        return _as_response(_lookup(session, test_id))


@router.patch("/cases/{test_id}", response_model=CaseResponse)
def update_case(test_id: str, body: UpdateCaseRequest) -> CaseResponse:
    """Change the latest version, or add one if it is already approved.

    Which of the two happens is not the caller's choice. An approved version is
    what a run was measured against, so it is never edited; asking to change one
    means asking for a new draft, and that is what comes back.
    """
    fields = body.model_dump(exclude_none=True)
    with session_scope() as session:
        case = _lookup(session, test_id)
        latest = case.versions[-1]
        if latest.is_approved:
            case_store.add_version(session, case, **fields)
        else:
            case_store.edit_draft(session, latest, **fields)
        session.refresh(case)
        return _as_response(case)


@router.post("/cases/{test_id}/freigeben", response_model=CaseResponse)
def approve_case(test_id: str) -> CaseResponse:
    """Approve the latest draft, making it the yardstick for future rounds."""
    with session_scope() as session:
        case = _lookup(session, test_id)
        try:
            case_store.approve(session, case.versions[-1])
        except case_store.IncompleteCase as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        session.refresh(case)
        return _as_response(case)


@router.post("/cases/{test_id}/zurueckziehen", response_model=CaseResponse)
def withdraw_case(test_id: str) -> CaseResponse:
    """Take a case out of future rounds. Its Test-ID stays spent."""
    with session_scope() as session:
        case = _lookup(session, test_id)
        case_store.withdraw(session, case)
        session.refresh(case)
        return _as_response(case)


@router.get("/kategorien", response_model=dict[str, str])
def kategorien() -> dict[str, str]:
    """The closed list a Test-ID can be built from, for the UI's dropdown."""
    return {str(k): name for k, name in KATEGORIE_NAMEN.items()}


def _lookup(session: object, test_id: str) -> Case:
    try:
        return case_store.get_case(session, test_id)  # type: ignore[arg-type]
    except case_store.UnknownCase as exc:
        raise HTTPException(status_code=404, detail=f"Testfall {test_id} nicht gefunden.") from exc


# ── Rounds (Phase 2 of the Vorlage) ─────────────────────────────────


def _run_response(session: Session, run: Run) -> RunResponse:
    state = run_store.progress(session, run)
    return RunResponse(
        id=run.id,
        label=run.label,
        status=run.status,
        sentra_base_url=run.sentra_base_url,
        repeats=run.repeats,
        started_at=run.started_at,
        completed_at=run.completed_at,
        fehler=run.fehler,
        stichprobe_seed=run.stichprobe_seed,
        stichprobe_anteil=run.stichprobe_anteil,
        total=state.total,
        done=state.done,
        failed=state.failed,
        audit_ok=run_store.audit_is_sound(session, run),
    )


@router.post("/runs", response_model=RunResponse, status_code=201)
def start_run(body: StartRunRequest, background: BackgroundTasks) -> RunResponse:
    """Start a round. Returns immediately; poll GET /runs/{id} for progress.

    A round is roughly 180 generation calls at 20 to 29 seconds each, so this
    cannot be a request that waits for its own result.
    """
    with session_scope() as session:
        try:
            run = run_store.start_run(
                session,
                label=body.label,
                repeats=body.repeats,
                stichprobe_anteil=body.stichprobe_anteil,
                stichprobe_seed=body.stichprobe_seed,
            )
        except run_store.RunnerError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        session.flush()
        response = _run_response(session, run)

    _EVAL_JOB.start(lambda: run_store.execute(response.id))
    return response


@router.get("/runs", response_model=list[RunResponse])
def list_runs() -> list[RunResponse]:
    with session_scope() as session:
        runs = session.execute(select(Run).order_by(Run.started_at.desc())).scalars()
        return [_run_response(session, run) for run in runs]


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: UUID) -> RunResponse:
    with session_scope() as session:
        return _run_response(session, _lookup_run(session, run_id))


@router.post("/runs/{run_id}/fortsetzen", response_model=RunResponse)
def resume_run(run_id: UUID) -> RunResponse:
    """Continue a round: make the calls that are missing, retry the ones that failed.

    A successful call is never repeated — it would spend quota to overwrite
    evidence that is already good.
    """
    with session_scope() as session:
        run = _lookup_run(session, run_id)
        run.status = LAUFEND
        run.completed_at = None
        run.fehler = ""
        response = _run_response(session, run)

    if not _EVAL_JOB.start(lambda: run_store.execute(run_id)):
        raise HTTPException(status_code=409, detail="Es läuft bereits eine Testrunde.")
    return response


@router.get("/runs/{run_id}/calls", response_model=list[CallResponse])
def list_calls(run_id: UUID) -> list[CallResponse]:
    """Every call the round has made so far, visible while it is still running."""
    with session_scope() as session:
        _lookup_run(session, run_id)
        rows = session.execute(
            select(Call, CaseVersion, Case)
            .join(CaseVersion, Call.case_version_id == CaseVersion.id)
            .join(Case, CaseVersion.case_id == Case.id)
            .where(Call.run_id == run_id)
            .order_by(Case.test_id, Call.variant_key, Call.repeat_index)
        ).all()
        return [
            CallResponse(
                id=call.id,
                test_id=case.test_id,
                variant_key=call.variant_key,
                repeat_index=call.repeat_index,
                status=call.status,
                endpoint=call.endpoint,
                http_status=call.http_status,
                dauer_ms=call.dauer_ms,
                fehler=call.fehler,
                zweck=call.zweck,
                request_body=call.request_body,
                response_body=call.response_body,
                checks=[
                    CheckResultResponse(
                        pruefung=c.pruefung,
                        ergebnis=c.ergebnis,
                        auffaellig=c.auffaellig,
                        belege=c.belege,
                    )
                    for c in session.execute(
                        select(CheckResult).where(CheckResult.call_id == call.id)
                    ).scalars()
                ],
            )
            for call, _version, case in rows
        ]


def _lookup_run(session: Session, run_id: UUID) -> Run:
    try:
        return run_store.get_run(session, run_id)
    except run_store.RunnerError as exc:
        raise HTTPException(status_code=404, detail=f"Testrunde {run_id} nicht gefunden.") from exc


# ── Stufe 2: the review queue ───────────────────────────────────────


@router.get("/runs/{run_id}/queue", response_model=list[QueueEntryResponse])
def review_queue(run_id: UUID) -> list[QueueEntryResponse]:
    """The cases a human still has to work through, with the yardstick attached.

    Carries no machine verdicts, deliberately. Section 6 of the Vorlage makes
    the disagreement rate between the automatic verdict and the human one the
    headline measurement, and a queue that handed the machine verdict over
    with the answer would leave the review screen hiding it only by choosing
    to. One careless render and that metric measures anchoring instead. See
    GET /calls/{id}/machine-verdicts, which the screen asks for after submit.
    """
    with session_scope() as session:
        _lookup_run(session, run_id)
        return [
            QueueEntryResponse(
                test_id=entry.test_id,
                kategorie=entry.kategorie,
                case_version_id=entry.case_version_id,
                version=entry.version,
                ausgangsfrage=entry.ausgangsfrage,
                erwartete_antwort=entry.erwartete_antwort,
                referenz_korrekt=entry.referenz_korrekt,
                referenz_falsch=entry.referenz_falsch,
                grenzfall=entry.grenzfall,
                gefunden_ueber=entry.gefunden_ueber,
                assessed=entry.assessed,
                calls=[
                    QueueCall(
                        id=call.id,
                        variant_key=call.variant_key,
                        repeat_index=call.repeat_index,
                        text=call.response_body.get("text") or "",
                        sources=call.response_body.get("sources") or [],
                        http_status=call.http_status,
                        dauer_ms=call.dauer_ms,
                    )
                    for call in entry.calls
                ],
            )
            for entry in review_store.queue(session, run_id)
        ]


@router.get("/calls/{call_id}/machine-verdicts", response_model=MachineVerdictsResponse)
def machine_verdicts(call_id: UUID) -> MachineVerdictsResponse:
    """What the checks concluded. Fetched after a human has submitted.

    Its own endpoint so that withholding it is the default rather than a
    decision the UI has to remember to make.
    """
    with session_scope() as session:
        try:
            per_call, per_group = review_store.machine_verdicts(session, call_id)
        except review_store.ReviewError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return MachineVerdictsResponse(
            per_call=[_check_response(c) for c in per_call],
            per_group=[_check_response(c) for c in per_group],
        )


@router.post(
    "/runs/{run_id}/cases/{case_version_id}/verdict",
    response_model=VerdictResponse,
    status_code=201,
)
def submit_verdict(
    run_id: UUID, case_version_id: UUID, body: SubmitVerdictRequest
) -> VerdictResponse:
    """Record one Phase-4 sheet. Every machine verdict stays where it is.

    Per case, not per call: `Reproduzierbar?` asks whether a finding recurred
    across the repeats, which no single answer can be asked, and
    `Kernbefund je Variante` is a field inside one sheet rather than a reason
    for several.
    """
    with session_scope() as session:
        try:
            verdict = review_store.record_verdict(
                session,
                run_id,
                case_version_id,
                tester=body.tester,
                kernbefunde=body.kernbefunde,
                quelle_4_3a=body.quelle_4_3a,
                quelle_4_3b=body.quelle_4_3b,
                quelle_4_3c=body.quelle_4_3c,
                schweregrad=body.schweregrad,
                reproduzierbar=body.reproduzierbar,
                anmerkung=body.anmerkung,
            )
        except review_store.AlreadyAssessed as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except review_store.ReviewError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _verdict_response(verdict)


@router.get("/runs/{run_id}/kisz", response_model=list[VerdictResponse])
def kisz_escalations(run_id: UUID) -> list[VerdictResponse]:
    """Schweregrad 3 and 4, which go to KISZ separately.

    Regardless of whether the case reached a human through Stufe 2 or the
    Stufe 3 sample, per section 5 of the Vorlage.
    """
    with session_scope() as session:
        _lookup_run(session, run_id)
        return [_verdict_response(v) for v in review_store.kisz_escalations(session, run_id)]


@router.get("/vorlage-optionen", response_model=VorlageOptions)
def vorlage_optionen() -> VorlageOptions:
    """The Phase-4 sheet's closed lists, for the review form.

    Served rather than copied into the frontend, for the reason #37 gave about
    prompts and filter options: two copies of a vocabulary drift, and this one
    has to keep matching a paper form.
    """
    return VorlageOptions(
        quelle_4_3a=[
            models.ZITAT_STIMMT,
            models.ZITAT_WEICHT_AB,
            models.ZITAT_EXISTIERT_NICHT,
            models.ZITAT_ENTFAELLT,
        ],
        quelle_4_3b=[models.QUELLE_KORREKT, models.QUELLE_FALSCH],
        quelle_4_3c=[models.KONTEXT_STUETZT, models.KONTEXT_STUETZT_NICHT],
        reproduzierbar=[
            models.REPRO_EINMALIG,
            models.REPRO_WIEDERHOLT,
            models.REPRO_ENTFAELLT,
        ],
        # Reported back so a screen can show how the case arrived; it is not
        # a field the form submits, because the server derives it.
        gefunden_ueber=[models.STUFE_2, models.STUFE_3, models.GRENZFALL_IMMER],
        schweregrad={1: "geringfügig", 2: "moderat", 3: "erheblich", 4: "kritisch"},
    )


def _check_response(result: CheckResult | GroupCheckResult) -> CheckResultResponse:
    """Both check tables carry the same four reporting fields, on purpose: a
    verdict about one call and a verdict about a group of repeats read the same
    way to a reviewer, and the trend report aggregates them the same way."""
    return CheckResultResponse(
        pruefung=result.pruefung,
        ergebnis=result.ergebnis,
        auffaellig=result.auffaellig,
        belege=result.belege,
    )


def _verdict_response(verdict: Verdict) -> VerdictResponse:
    return VerdictResponse(
        id=verdict.id,
        run_id=verdict.run_id,
        case_version_id=verdict.case_version_id,
        tester=verdict.tester,
        kernbefunde=verdict.kernbefunde,
        gefunden_ueber=verdict.gefunden_ueber,
        quelle_4_3a=verdict.quelle_4_3a,
        quelle_4_3b=verdict.quelle_4_3b,
        quelle_4_3c=verdict.quelle_4_3c,
        schweregrad=verdict.schweregrad,
        reproduzierbar=verdict.reproduzierbar,
        anmerkung=verdict.anmerkung,
        kisz_meldung=verdict.kisz_meldung,
        created_at=verdict.created_at,
    )


@router.get("/runs/{run_id}/triage", response_model=TriageSummary)
def triage_summary(run_id: UUID) -> TriageSummary:
    """What Stufe 1 decided, in aggregate.

    A round where everything is flagged means the threshold filters nothing; a
    round where nothing is may mean it filters too much. That ratio is what the
    Vorlage's headline metric is calibrating, so it is worth seeing without
    counting a queue by hand.
    """
    with session_scope() as session:
        run = _lookup_run(session, run_id)
        decisions = triage.triage_run(session, run)
        return TriageSummary(
            gesamt=len(decisions),
            stufe_2=sum(1 for d in decisions if d.gefunden_ueber == models.STUFE_2),
            stufe_3=sum(1 for d in decisions if d.gefunden_ueber == models.STUFE_3),
            grenzfaelle=sum(1 for d in decisions if d.gefunden_ueber == models.GRENZFALL_IMMER),
            unauffaellig=sum(1 for d in decisions if not d.needs_review),
        )


# ── Phase 4: documentation and the trend report ─────────────────────


@router.get("/runs/{run_id}/boegen", response_model=list[SheetResponse])
def documentation_sheets(run_id: UUID) -> list[SheetResponse]:
    """The round's Phase-4 sheets, one per case, ready to hand to KISZ.

    Machine verdicts appear here even though the review queue withholds them.
    Withhold while somebody is forming an assessment; include in the record
    afterwards — a sheet that hid what the automation concluded would make the
    disagreement rate uncheckable by whoever receives it.
    """
    with session_scope() as session:
        run = _lookup_run(session, run_id)
        return [SheetResponse(**vars(sheet)) for sheet in report_store.sheets(session, run)]


@router.get("/runs/{run_id}/abweichung", response_model=AgreementResponse)
def agreement(run_id: UUID) -> AgreementResponse:
    """How often Stufe 1 and the human reached the same conclusion.

    Section 6 calls this the most important number in the process: it is what
    says whether the Prüfschwelle is set too generously or too strictly.
    """
    with session_scope() as session:
        run = _lookup_run(session, run_id)
        found = report_store.agreement(session, run)
        return AgreementResponse(
            einig=found.einig,
            zu_streng=found.zu_streng,
            zu_grosszuegig=found.zu_grosszuegig,
            nicht_bewertet=found.nicht_bewertet,
            abweichungsquote=found.abweichungsquote,
        )


@router.get("/trend", response_model=TrendResponse)
def trend_report() -> TrendResponse:
    """The Trendauswertung across every round, section 6.

    Where findings cluster, which categories are unstable, and the
    disagreement rate combined over all rounds. Derived from stored rows, so
    running it again over old rounds gives the same answer.
    """
    with session_scope() as session:
        found = report_store.trend(session)
        return TrendResponse(
            runden=found.runden,
            faelle=found.faelle,
            nach_kategorie=found.nach_kategorie,
            schweregrade=found.schweregrade,
            kisz_meldungen=found.kisz_meldungen,
            haeufigste_befunde=found.haeufigste_befunde,
            abweichung=AgreementResponse(**found.abweichung),
        )


# ── 4.2: paraphrase variants ────────────────────────────────────────


def _variant_response(variant: models.Variant) -> VariantResponse:
    return VariantResponse(
        stil=variant.stil,
        wortlaut=variant.wortlaut,
        status=variant.status,
        erstellt_durch=variant.erstellt_durch,
        freigegeben_durch=variant.freigegeben_durch,
        freigegeben_at=variant.freigegeben_at,
    )


@router.get("/cases/{test_id}/varianten", response_model=list[VariantResponse])
def list_variants(test_id: str) -> list[VariantResponse]:
    """The paraphrases for the case's latest version, proposed or approved."""
    with session_scope() as session:
        case = _lookup(session, test_id)
        return [
            _variant_response(v) for v in variant_store.for_version(session, case.versions[-1].id)
        ]


@router.post("/cases/{test_id}/varianten/vorschlagen", response_model=list[VariantResponse])
def propose_variants(test_id: str) -> list[VariantResponse]:
    """Ask the judge model for three paraphrases.

    The judge model rather than CHAT_MODEL: letting the system under test write
    its own paraphrases would let it rephrase in whatever way it finds easiest
    to answer, which is the opposite of a robustness check.

    They arrive as proposals. Only a person can approve one, because a variant
    that quietly asks a different question does not measure robustness.
    """
    with session_scope() as session:
        case = _lookup(session, test_id)
        try:
            proposed = variant_store.propose(session, case.versions[-1])
        except JudgeUnavailable as exc:
            raise HTTPException(
                status_code=503, detail=f"Varianten konnten nicht erzeugt werden: {exc}"
            ) from exc
        return [_variant_response(v) for v in proposed]


@router.patch("/cases/{test_id}/varianten/{stil}", response_model=VariantResponse)
def edit_variant(test_id: str, stil: str, body: EditVariantRequest) -> VariantResponse:
    """Correct a proposal. An approved variant is frozen."""
    with session_scope() as session:
        variant = _lookup_variant(session, test_id, stil)
        try:
            variant_store.edit(session, variant, body.wortlaut)
        except variant_store.ApprovedVariantIsFrozen as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _variant_response(variant)


@router.post("/cases/{test_id}/varianten/{stil}/freigeben", response_model=VariantResponse)
def approve_variant(test_id: str, stil: str, body: ApproveVariantRequest) -> VariantResponse:
    """A person has read this and confirmed it asks the same question.

    Only approved variants are ever run, so this is what puts one into a round.
    """
    with session_scope() as session:
        variant = _lookup_variant(session, test_id, stil)
        try:
            variant_store.approve(session, variant, freigegeben_durch=body.freigegeben_durch)
        except variant_store.VariantError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _variant_response(variant)


def _lookup_variant(session: Session, test_id: str, stil: str) -> models.Variant:
    case = _lookup(session, test_id)
    for variant in variant_store.for_version(session, case.versions[-1].id):
        if variant.stil == stil:
            return variant
    raise HTTPException(status_code=404, detail=f"Variante {stil} nicht gefunden.")
