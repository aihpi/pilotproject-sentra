"""The harness's own API surface, mounted at /api/eval.

Its response models live here rather than in sentra.api.models, and an
import-linter contract keeps them there. The harness is a separate concern with
a separate audience — Hotline and WD working through a round, not somebody
searching documents — and letting the two share models is how services/explorer.py
ended up importing from the API layer.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from sentra.evaluation import cases as case_store
from sentra.evaluation.categories import KATEGORIE_NAMEN
from sentra.evaluation.config import EvalSettings, get_eval_settings
from sentra.evaluation.db import EvalDatabaseUnavailable, schema_revision, session_scope
from sentra.evaluation.judge import judge_config
from sentra.evaluation.models import Case
from sentra.evaluation.schemas import (
    CaseResponse,
    CaseVersionResponse,
    CreateCaseRequest,
    EvalHealthResponse,
    UpdateCaseRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eval", tags=["evaluation"])


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
