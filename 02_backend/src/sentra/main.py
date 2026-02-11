import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentra.api.routes import router
from sentra.config import get_settings
from sentra.rag.store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup and shutdown lifecycle."""
    settings = get_settings()
    store = VectorStore(settings)
    store.ensure_collection()
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
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
