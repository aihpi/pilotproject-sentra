"""The evaluation harness as its own application.

Beside SENTRA, not inside it. The harness measures SENTRA, and something that
cannot be restarted without restarting the thing it measures is not
independent whatever its import graph says. It also means a round in progress
does not end because somebody deployed SENTRA, and that SENTRA's availability
never depends on the harness's database.

The boundary was always HTTP — the runner has called SENTRA at
SENTRA_BASE_URL from the start, because the API layer is part of what is under
test — so separating the processes changed the entrypoint and the packaging and
nothing about how a round works.

    uvicorn sentra_eval.app:app --port 8100

nginx routes /api/eval here and everything else to SENTRA, so a browser still
sees a single origin and the frontend needs no CORS of its own.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sentra_eval.config import get_eval_settings
from sentra_eval.db import EvalDatabaseUnavailable
from sentra_eval.judge import judge_config
from sentra_eval.router import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

# German, like every other message a caller can read.
DATABASE_UNAVAILABLE = (
    "Die Datenbank der Auswertung ist nicht erreichbar. Bitte den Betrieb informieren."
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Refuse to start without an independent judge.

    At startup rather than on first use. A round is about 180 generation calls;
    discovering afterwards that every consistency verdict was SENTRA grading
    itself would mean discarding the lot. The Vorlage is explicit that the
    checking model must not be the same model as the one under test.

    The database is deliberately not checked here. The harness has to come up
    and say what is wrong through /api/eval/health, rather than crash-looping
    while somebody is trying to find out why.
    """
    settings = get_eval_settings()
    judge = judge_config()

    if judge.model == settings.chat_model_under_test:
        raise RuntimeError(
            f"JUDGE_MODEL and CHAT_MODEL are both {judge.model!r}. The judge has to be a "
            f"different model, or its verdicts only say that SENTRA agrees with itself."
        )

    logger.info(
        "Evaluation harness ready — judge %s, SENTRA at %s",
        judge.model,
        settings.sentra_base_url,
    )
    yield


def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """The eval database is down.

    The harness's own policy now. It used to be registered from api/errors.py,
    passed in as an exception class, because `api` importing the harness would
    have loaded it into every SENTRA process. Separate applications make that
    contortion unnecessary: this is the only app that has an eval database, so
    it is the app that says what happens when it is missing.
    """
    logger.warning("Eval database unavailable for %s: %s", request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": DATABASE_UNAVAILABLE})


def create_app() -> FastAPI:
    """Build the harness app. A factory, so tests get a fresh one."""
    app = FastAPI(
        title="Sentra Evaluation",
        description=(
            "Structured test rounds for SENTRA, per the KISZ Testverfahren. "
            "Runs against SENTRA over HTTP; shares no process with it."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        # Only the vite dev server calls this cross-origin. Under compose nginx
        # routes /api/eval here, so the browser sees one origin and CORS never
        # applies — the same arrangement SENTRA has.
        allow_origins=get_eval_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(EvalDatabaseUnavailable, _database_unavailable)
    app.include_router(router)
    return app


app = create_app()
