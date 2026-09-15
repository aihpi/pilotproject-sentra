"""Running the ingestion in the background, and refusing to run two.

This used to live in the POST /ingest handler, which read the progress
singleton, decided nothing was running, and spawned a daemon thread. Two
problems with that, beyond a request handler knowing about threads at all.

The decision and the spawn were separate steps with nothing holding them
together, and the status they read is only set to "running" by the run itself,
from inside the new thread, after start() has already returned. Two requests
arriving together could both look, both see "idle", and both spawn: reproduced
in roughly one attempt in three. Two ingestions then write to the same
collection, spend AI Hub quota twice over, and overwrite each other's
progress. FastAPI serves sync handlers from a threadpool, so this needs no
more than someone clicking the button twice.

Nothing held the thread either, so nothing could ask whether it was still
alive. The only signal was a status string, which stays "running" for good if
a run ever dies without setting it.

Both go away by making one object own the thread: the check and the start
happen under its lock, and "is it running" asks the thread rather than a
string.

Single process only, deliberately. Two replicas each get their own lock and
can each start a run, which is the same limitation the progress singleton
already has. Fixing it means moving this state out of the process, and this
module is the place that would change.
"""

import logging
import threading

from sentra.config import Settings
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.store import VectorStore
from sentra.services.ingest import run_ingestion

logger = logging.getLogger(__name__)


class IngestionJob:
    """Owns the ingestion thread and the decision to start one."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(
        self,
        store: VectorStore,
        embedder: EmbeddingClient,
        settings: Settings,
        force: bool = False,
    ) -> bool:
        """Start a run, or report that one is already going.

        Returns False rather than raising: whether that becomes a 409 is the
        router's business, not this module's.
        """
        with self._lock:
            if self._is_running():
                logger.info("Ingestion already running, not starting another")
                return False

            logger.info("Starting ingestion (force=%s)", force)
            self._thread = threading.Thread(
                target=run_ingestion,
                args=(store, embedder, settings, force),
                daemon=True,
                name="ingestion",
            )
            self._thread.start()
            return True

    def is_running(self) -> bool:
        with self._lock:
            return self._is_running()

    def _is_running(self) -> bool:
        """Caller holds the lock.

        Asks the thread, not the reported status. A run that dies without
        setting its own status would otherwise block every later run for the
        lifetime of the process.
        """
        return self._thread is not None and self._thread.is_alive()
