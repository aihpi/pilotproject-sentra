"""One job, one thread, whatever the callers do.

The two properties #51 established, now that they live somewhere both ingestion
and the evaluation harness can reach. They are worth testing directly rather
than only through ingestion, because the next module to use this will have
neither Qdrant nor an AI Hub to exercise it through.
"""

import threading
import time

from sentra.jobs import BackgroundJob


def _blocks_until(event: threading.Event):
    def work() -> None:
        event.wait(timeout=5)

    return work


class TestOneAtATime:
    def test_a_second_start_is_refused_while_the_first_runs(self):
        release = threading.Event()
        job = BackgroundJob("test")

        assert job.start(_blocks_until(release)) is True
        assert job.start(_blocks_until(release)) is False

        release.set()

    def test_simultaneous_starts_produce_one_run(self):
        """The bug this exists for. The old code read a status string that the
        run itself only set from inside the new thread, after start() had
        returned, so two requests could both see "idle" and both spawn — about
        one attempt in three.
        """
        release = threading.Event()
        job = BackgroundJob("test")
        started: list[bool] = []
        barrier = threading.Barrier(8)

        def racer() -> None:
            barrier.wait()
            started.append(job.start(_blocks_until(release)))

        threads = [threading.Thread(target=racer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        release.set()
        assert started.count(True) == 1, f"{started.count(True)} runs started, expected 1"

    def test_a_new_run_can_start_once_the_first_finishes(self):
        job = BackgroundJob("test")
        job.start(lambda: None)
        for _ in range(500):
            if not job.is_running():
                break
            time.sleep(0.002)

        assert job.start(lambda: None) is True


class TestItAsksTheThread:
    def test_a_job_that_dies_does_not_block_the_next_one(self):
        """The other bug. Status was a string the run set for itself, so a run
        that raised left it saying "running" for the life of the process."""
        job = BackgroundJob("test")

        def explodes() -> None:
            raise RuntimeError("boom")

        job.start(explodes)
        for _ in range(500):
            if not job.is_running():
                break
            time.sleep(0.002)

        assert job.is_running() is False
        assert job.start(lambda: None) is True

    def test_nothing_is_running_before_anything_starts(self):
        assert BackgroundJob("test").is_running() is False
