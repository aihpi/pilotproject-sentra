"""The harness's own API surface, mounted at /api/eval.

Its response models live here rather than in sentra.api.models, and an
import-linter contract keeps them there. The harness is a separate concern with
a separate audience — Hotline and WD working through a round, not somebody
searching documents — and letting the two share models is how services/explorer.py
ended up importing from the API layer.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from sentra.evaluation.config import EvalSettings, get_eval_settings
from sentra.evaluation.db import EvalDatabaseUnavailable, schema_revision

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eval", tags=["evaluation"])


class EvalHealthResponse(BaseModel):
    status: str
    judge_model: str
    sentra_base_url: str
    database: str
    schema_revision: str | None = None


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
        judge_model=settings.judge_model,
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
