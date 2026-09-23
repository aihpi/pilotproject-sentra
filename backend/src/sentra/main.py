import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from sentra.api.auth import warn_if_open
from sentra.api.errors import register_error_handlers
from sentra.api.identity import login_configured
from sentra.api.routes import router
from sentra.config import get_settings
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.generator import AnswerGenerator
from sentra.rag.store import VectorStore
from sentra.services.jobs import IngestionJob

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown lifecycle.

    Creates shared client instances stored on app.state so they are
    reused across all requests instead of being created per-request.
    """
    settings = get_settings()

    # Before anything else, because it is about how this instance is exposed
    # rather than whether it works. An unset token leaves the write path and
    # the feedback read path open, and that has to be said somewhere an
    # operator sees it — /api/health carries the same fact for anyone who is
    # not reading logs.
    warn_if_open(settings)

    store = VectorStore(settings)
    # Before creating anything: an existing collection built for a different
    # vector width cannot serve our vectors, so every query would fail. Better
    # to refuse here than to come up healthy and fail on first search.
    store.verify_dimensions()
    store.ensure_collection()
    store.ensure_doc_collection()

    embedder = EmbeddingClient(settings)
    generator = AnswerGenerator(settings)

    app.state.store = store
    app.state.embedder = embedder
    app.state.generator = generator
    app.state.ingestion_job = IngestionJob()

    info = store.collection_info()
    logger.info("Qdrant ready — %d points indexed", info["points_count"])
    yield


app = FastAPI(
    title="Sentra RAG API",
    description="RAG prototype for the German Bundestag Wissenschaftliche Dienste",
    version="0.1.0",
    lifespan=lifespan,
)

# Before CORS in source order, which means it runs outside it: the session has
# to be readable by the time a route runs, and Starlette applies middleware in
# reverse.
#
# Only mounted when a login is configured. A SessionMiddleware with an empty
# secret key is a signed cookie anybody can forge, so the absence of a secret
# has to mean the absence of sessions rather than weak ones.
if login_configured(get_settings()):
    app.add_middleware(
        SessionMiddleware,
        secret_key=get_settings().session_secret,
        session_cookie="sentra_session",
        max_age=get_settings().session_max_age_seconds,
        same_site="lax",
        https_only=get_settings().session_cookie_secure,
    )

app.add_middleware(
    CORSMiddleware,
    # Only the vite dev server calls this cross-origin. Under docker compose
    # nginx proxies /api, so the browser sees one origin and CORS never applies.
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)
app.include_router(router)
