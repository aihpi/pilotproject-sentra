"""Running work in the background, and refusing to run two of it.

A copy, and deliberately one. The same code lives in `sentra.jobs`, where it
was extracted from ingestion in #81 so that this harness could share it — which
was right while the harness was a module inside SENTRA's package. It is not a
shared module any more: depending on `sentra` to get forty lines of thread and
lock would pull docling and qdrant-client into an image that parses no PDFs and
searches no vectors, and would reintroduce exactly the coupling that moving out
of `backend/` was meant to remove.

So: forty duplicated lines, in exchange for a distribution that depends on
nothing of SENTRA's. If the two ever drift, this one is the harness's.

The reasoning below is #51's, and it is why this is not simply
`threading.Thread(...).start()`.

The check and the start have to happen together, under one lock. Ingestion's
version once read a progress singleton, saw "idle", and spawned a thread, with
nothing holding the two steps together. The status it read is only set to
"running" by the run itself, from inside the new thread, after start() has
already returned. Two requests arriving together could both look, both see
"idle", and both spawn — reproduced in roughly one attempt in three. FastAPI
serves sync handlers from a threadpool, so this needs no more than someone
clicking a button twice.

And "is it running" has to ask the thread, not a status string. A run that died
without setting its own status left the string saying "running" for the life of
the process, blocking every later run.

Single process only, deliberately. Two replicas each get their own lock and can
each start a round, which for this harness means spending the hub quota twice.
Fixing that means moving this state out of the process, and this module is
where that would happen.
"""

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class BackgroundJob:
    """Owns a thread and the decision to start one."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self, work: Callable[[], None]) -> bool:
        """Start `work` in a thread, or report that one is already going."""
        with self._lock:
            if self._is_running():
                logger.info("%s already running, not starting another", self._name)
                return False

            logger.info("Starting %s", self._name)
            self._thread = threading.Thread(target=work, daemon=True, name=self._name)
            self._thread.start()
            return True

    def is_running(self) -> bool:
        with self._lock:
            return self._is_running()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the current run finishes. Returns whether it did."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def _is_running(self) -> bool:
        """Caller holds the lock. Asks the thread, not a reported status."""
        return self._thread is not None and self._thread.is_alive()
