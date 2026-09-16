"""The harness's own API surface, mounted at /api/eval.

Its response models live here rather than in sentra.api.models, and an
import-linter contract keeps them there. The harness is a separate concern with
a separate audience — Hotline and WD working through a round, not somebody
searching documents — and letting the two share models is how services/explorer.py
ended up importing from the API layer.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from sentra.evaluation.config import EvalSettings, get_eval_settings

router = APIRouter(prefix="/api/eval", tags=["evaluation"])


class EvalHealthResponse(BaseModel):
    status: str
    judge_model: str
    sentra_base_url: str


@router.get("/health", response_model=EvalHealthResponse)
def health(settings: EvalSettings = Depends(get_eval_settings)) -> EvalHealthResponse:
    """Whether the harness is mounted, and what it is pointed at.

    Reaching this at all is the answer to the first question: the router is
    only mounted when EVAL_ENABLED is set. The two values say which judge the
    verdicts will come from and which SENTRA the runner will call, both of
    which are worth being able to read off a running instance rather than
    inferring from a deployment.

    The API key is deliberately not here.
    """
    return EvalHealthResponse(
        status="ok",
        judge_model=settings.judge_model,
        sentra_base_url=settings.sentra_base_url,
    )
