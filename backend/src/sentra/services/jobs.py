"""Running the ingestion in the background.

The thread-and-lock reasoning that used to be here moved to sentra.jobs when
the evaluation harness needed the same guarantees; the layering contract puts
evaluation below services, so a shared module had to sit lower than both. What
is left here is the part that is actually about ingestion.
"""

import logging

from sentra.config import Settings
from sentra.jobs import BackgroundJob
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.store import VectorStore
from sentra.services.ingest import run_ingestion

logger = logging.getLogger(__name__)


class IngestionJob:
    """Starts an ingestion run, and refuses to start a second one."""

    def __init__(self) -> None:
        self._job = BackgroundJob("ingestion")

    def start(
        self,
        store: VectorStore,
        embedder: EmbeddingClient,
        settings: Settings,
        force: bool = False,
    ) -> bool:
        """Start a run, or report that one is already going."""
        logger.info("Ingestion requested (force=%s)", force)
        return self._job.start(lambda: run_ingestion(store, embedder, settings, force))

    def is_running(self) -> bool:
        return self._job.is_running()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the current run finishes. Returns whether it did."""
        return self._job.wait(timeout)
