import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentra.api.errors import register_error_handlers
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
