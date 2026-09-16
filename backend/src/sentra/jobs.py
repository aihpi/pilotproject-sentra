"""Running work in the background, and refusing to run two of it.

Extracted from services/jobs.py, where it was written for ingestion, because
the evaluation harness needs the same thing and the layering contract puts it
below services. The reasoning below is #51's and belongs with the code it
explains — it is the record of why this is not simply
`threading.Thread(...).start()`, and it is what should stop someone reducing it
back to that.

The check and the start have to happen together, under one lock. Ingestion's
version once read a progress singleton, saw "idle", and spawned a thread, with
nothing holding the two steps together. The status it read is only set to
"running" by the run itself, from inside the new thread, after start() has
already returned. Two requests arriving together could both look, both see
"idle", and both spawn — reproduced in roughly one attempt in three. FastAPI
serves sync handlers from a threadpool, so this needs no more than someone
clicking a button twice.

And "is it running" has to ask the thread, not a status string. Nothing held
the thread, so nothing could ask. A run that died without setting its own
status left the string saying "running" for the life of the process, blocking
every later run.

Single process only, deliberately. Two replicas each get their own lock and can
each start a run, which is the same limitation the progress singletons already
have. Fixing that means moving this state out of the process, and this module
is where that would happen.
"""

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class BackgroundJob:
    """Owns a thread and the decision to start one.

    Generic on purpose: it knows how to not start twice and nothing about what
    it is running. Callers wrap it with whatever their own start() needs to
    take — see services/jobs.py:IngestionJob.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self, work: Callable[[], None]) -> bool:
        """Start `work` in a thread, or report that one is already going.

        Returns False rather than raising: whether that becomes a 409 is the
        router's business, not this module's.
        """
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
        """Block until the current run finishes. Returns whether it did.

        For tests and for shutdown. Twelve places were reaching into the
        thread attribute to do this, which is the coupling that made this
        extraction fail the first time — waiting for a job is a real thing to
        want and deserves to be askable.
        """
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def _is_running(self) -> bool:
        """Caller holds the lock. Asks the thread, not a reported status."""
        return self._thread is not None and self._thread.is_alive()
