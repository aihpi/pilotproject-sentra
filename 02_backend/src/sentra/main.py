import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentra.api.routes import router
from sentra.config import get_settings
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.generator import AnswerGenerator
from sentra.rag.store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle.

    Creates shared client instances stored on app.state so they are
    reused across all requests instead of being created per-request.
    """
    settings = get_settings()

    store = VectorStore(settings)
    store.ensure_collection()
    store.ensure_doc_collection()

    embedder = EmbeddingClient(settings)
    generator = AnswerGenerator(settings)

    app.state.store = store
    app.state.embedder = embedder
    app.state.generator = generator

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
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
