"""Starting the ingestion, and refusing to start a second one.

This lived in the POST /ingest handler as a read of the progress singleton
followed by a thread spawn, with nothing holding the two together. The status
it read is set by the run itself, from inside the new thread, so two requests
arriving together could both see "idle" and both spawn. Reproduced in about
one attempt in three before this change.

The concurrency test below is the point of the module. It drives many threads
at start() at once through a barrier and insists exactly one run happens.

Offline: run_ingestion is stubbed everywhere, so no Docling, Qdrant or AI Hub.
"""

import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentra.api.routes import get_embedder, get_ingestion_job, get_store, router
from sentra.config import get_settings
from sentra.services import jobs
from sentra.services.jobs import IngestionJob


class Recorder:
    """Stands in for run_ingestion, counting runs and holding them open."""

    def __init__(self, block: threading.Event | None = None):
        self.runs = 0
        self.args: list[tuple] = []
        self._block = block
        self._lock = threading.Lock()

    def __call__(self, store, embedder, settings, force):
        with self._lock:
            self.runs += 1
            self.args.append((store, embedder, settings, force))
        if self._block is not None:
            self._block.wait(timeout=5)


def started(job: IngestionJob, recorder: Recorder, monkeypatch, **kwargs) -> bool:
    monkeypatch.setattr(jobs, "run_ingestion", recorder)
    return job.start("store", "embedder", "settings", **kwargs)


class TestStarting:
    def test_first_start_runs_it(self, monkeypatch):
        job, recorder = IngestionJob(), Recorder()
        assert started(job, recorder, monkeypatch) is True

        job._thread.join(timeout=5)
        assert recorder.runs == 1

    def test_arguments_are_passed_through(self, monkeypatch):
        job, recorder = IngestionJob(), Recorder()
        started(job, recorder, monkeypatch, force=True)

        job._thread.join(timeout=5)
        assert recorder.args == [("store", "embedder", "settings", True)]

    def test_force_defaults_to_false(self, monkeypatch):
        job, recorder = IngestionJob(), Recorder()
        started(job, recorder, monkeypatch)

        job._thread.join(timeout=5)
        assert recorder.args[0][3] is False


class TestRefusingASecond:
    def test_second_start_is_refused_while_the_first_runs(self, monkeypatch):
        block = threading.Event()
        job, recorder = IngestionJob(), Recorder(block=block)

        assert started(job, recorder, monkeypatch) is True
        assert job.is_running() is True
        assert job.start("store", "embedder", "settings") is False

        block.set()
        job._thread.join(timeout=5)
        assert recorder.runs == 1

    def test_a_new_run_is_allowed_once_the_first_finishes(self, monkeypatch):
        job, recorder = IngestionJob(), Recorder()

        assert started(job, recorder, monkeypatch) is True
        job._thread.join(timeout=5)

        assert job.is_running() is False
        assert job.start("store", "embedder", "settings") is True
        job._thread.join(timeout=5)
        assert recorder.runs == 2

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_a_run_that_raises_does_not_block_the_next_one(self, monkeypatch):
        """Liveness comes from the thread, not from a reported status.

        run_ingestion catches its own errors today, but if one ever escaped, a
        status-based guard would refuse every later run for the lifetime of
        the process.
        """
        job = IngestionJob()

        def explode(*args):
            raise RuntimeError("boom")

        monkeypatch.setattr(jobs, "run_ingestion", explode)
        assert job.start("store", "embedder", "settings") is True
        job._thread.join(timeout=5)

        assert job.is_running() is False
        recorder = Recorder()
        assert started(job, recorder, monkeypatch) is True
        job._thread.join(timeout=5)
        assert recorder.runs == 1


class TestConcurrentStarts:
    """The race this module exists to close."""

    def test_only_one_of_many_simultaneous_starts_wins(self, monkeypatch):
        block = threading.Event()
        job, recorder = IngestionJob(), Recorder(block=block)
        monkeypatch.setattr(jobs, "run_ingestion", recorder)

        callers = 12
        barrier = threading.Barrier(callers)
        results: list[bool] = []
        results_lock = threading.Lock()

        def caller():
            barrier.wait(timeout=5)
            outcome = job.start("store", "embedder", "settings")
            with results_lock:
                results.append(outcome)

        threads = [threading.Thread(target=caller) for _ in range(callers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert sum(results) == 1, f"{sum(results)} callers were told they started"

        block.set()
        job._thread.join(timeout=5)
        assert recorder.runs == 1, f"{recorder.runs} ingestions ran"


class TestThroughTheEndpoint:
    """What the router is left doing: turning False into a 409."""

    def client(self, job, settings):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_store] = lambda: "store"
        app.dependency_overrides[get_embedder] = lambda: "embedder"
        app.dependency_overrides[get_ingestion_job] = lambda: job
        return TestClient(app)

    def test_start_answers_200(self, settings, monkeypatch):
        job, recorder = IngestionJob(), Recorder()
        monkeypatch.setattr(jobs, "run_ingestion", recorder)

        response = self.client(job, settings).post("/api/ingest")

        assert response.status_code == 200
        assert response.json() == {"status": "started"}
        job._thread.join(timeout=5)

    def test_a_second_request_answers_409(self, settings, monkeypatch):
        block = threading.Event()
        job, recorder = IngestionJob(), Recorder(block=block)
        monkeypatch.setattr(jobs, "run_ingestion", recorder)
        client = self.client(job, settings)

        assert client.post("/api/ingest").status_code == 200
        assert client.post("/api/ingest").status_code == 409

        block.set()
        job._thread.join(timeout=5)
        assert recorder.runs == 1

    def test_force_reaches_the_job(self, settings, monkeypatch):
        job, recorder = IngestionJob(), Recorder()
        monkeypatch.setattr(jobs, "run_ingestion", recorder)

        self.client(job, settings).post("/api/ingest?force=true")
        job._thread.join(timeout=5)

        assert recorder.args[0][3] is True
