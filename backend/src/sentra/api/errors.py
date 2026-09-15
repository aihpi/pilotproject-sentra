"""One place deciding what a failed request answers.

The router used to hold three policies at once. /documents caught bare
Exception and returned an empty list, so an unreachable Qdrant looked
identical to an empty index. /health caught and reported "degraded". The five
explorer endpoints caught nothing, so any dependency failure surfaced as a 500
with a stack trace. The frontend could not tell "nothing found" from "nothing
working".

The policy now:

  503  a dependency we need is unavailable, unauthorised or misconfigured.
       Nothing the caller can fix, and nothing about their request was wrong.
  4xx  the request itself was wrong. Raised as HTTPException at the point that
       knows why, and passed through here untouched.
  500  anything we did not anticipate, which means a bug. Logged with its
       traceback, and deliberately not dressed up as something else.

Exception classes rather than call sites, so an endpoint added later gets the
policy without having to remember it.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from openai import OpenAIError
from qdrant_client.http.exceptions import ApiException as QdrantApiException

from sentra.rag.store import DimensionMismatch

logger = logging.getLogger(__name__)

# German, because every other message the user can see is German.
SEARCH_UNAVAILABLE = "Die Suchdatenbank ist nicht erreichbar. Bitte später erneut versuchen."
AI_UNAVAILABLE = "Der KI-Dienst ist nicht erreichbar. Bitte später erneut versuchen."
MISCONFIGURED = "Der Suchindex ist falsch konfiguriert. Bitte den Betrieb informieren."


def _unavailable(detail: str) -> JSONResponse:
    """Same body shape as HTTPException produces, so callers parse one format."""
    return JSONResponse(status_code=503, content={"detail": detail})


def _qdrant_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """Qdrant unreachable, or reachable and refusing.

    Both subclasses land here. ResponseHandlingException means we could not
    talk to it; UnexpectedResponse means it answered with an error, which for
    us is a deployment problem rather than a caller problem. An absent
    collection is the one case that is genuinely not an error, and /documents
    checks for that explicitly instead of letting it come through here.
    """
    logger.warning("Qdrant unavailable for %s: %s", request.url.path, exc)
    return _unavailable(SEARCH_UNAVAILABLE)


def _ai_hub_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """The AI Hub: unreachable, rate-limiting, or rejecting our key.

    All of it is 503. A bad key is a misconfiguration rather than a passing
    outage, so the wording is a compromise, but from the caller's side the
    service is equally unavailable and there is equally nothing to do about
    it. The log line carries the real cause.
    """
    logger.warning("AI Hub unavailable for %s: %s", request.url.path, exc)
    return _unavailable(AI_UNAVAILABLE)


def _misconfigured(request: Request, exc: Exception) -> JSONResponse:
    """A collection built for a different vector width.

    Startup already refuses this, so reaching it here means the collection
    changed under a running process.
    """
    logger.error("Configuration mismatch for %s: %s", request.url.path, exc)
    return _unavailable(MISCONFIGURED)


def register_error_handlers(app: FastAPI) -> None:
    """Attach the policy. Called once, from main."""
    app.add_exception_handler(QdrantApiException, _qdrant_unavailable)
    app.add_exception_handler(OpenAIError, _ai_hub_unavailable)
    app.add_exception_handler(DimensionMismatch, _misconfigured)
