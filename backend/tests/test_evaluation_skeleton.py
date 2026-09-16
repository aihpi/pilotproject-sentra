"""The harness is mounted only when it is switched on, and only next to a judge
that is not SENTRA.

Two properties this task exists to establish, both of which get more expensive
to retrofit the more the harness grows:

  - EVAL_ENABLED off leaves the application exactly what it was. Not "the
    routes 404" — the package is never imported, which is what lets its
    dependencies be an extra that a production image can leave out.
  - a judge configured as CHAT_MODEL stops the deployment. A round is about 180
    generation calls; finding out afterwards that every consistency verdict was
    the model grading itself means discarding all of them.

Offline. Nothing here reaches the judge or the hub — the settings are read, the
clients are not built.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentra.api.routes import router as core_router
from sentra.evaluation import JudgeNotIndependent, get_eval_settings
from sentra.main import mount_evaluation

BACKEND = Path(__file__).resolve().parents[1]

# A judge that could not be reached if anything tried, on a model name nothing
# else in the suite uses.
JUDGE_HUB = "http://judge.invalid/v1"
JUDGE_MODEL = "a-judge-that-is-not-the-chat-model"


@pytest.fixture
def judge_configured(monkeypatch):
    """Judge credentials in the environment, and the cache cleared around it.

    get_eval_settings is lru_cached, like get_settings, so a test that changed
    the environment without clearing it would be read by the next one.
    """
    monkeypatch.setenv("JUDGE_BASE_URL", JUDGE_HUB)
    monkeypatch.setenv("JUDGE_API_KEY", "not-a-real-key")
    monkeypatch.setenv("JUDGE_MODEL", JUDGE_MODEL)
    get_eval_settings.cache_clear()
    yield
    get_eval_settings.cache_clear()


@pytest.fixture
def enabled(settings):
    return settings.model_copy(update={"eval_enabled": True})


# ── Switched on ─────────────────────────────────────────────────────


class TestMountedWhenEnabled:
    def test_health_responds(self, judge_configured, enabled):
        app = FastAPI()
        mount_evaluation(app, enabled)

        response = TestClient(app).get("/api/eval/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_says_which_judge_and_which_sentra(self, judge_configured, enabled):
        app = FastAPI()
        mount_evaluation(app, enabled)

        body = TestClient(app).get("/api/eval/health").json()

        assert body["judge_model"] == JUDGE_MODEL
        assert body["sentra_base_url"]

    def test_health_does_not_leak_the_key(self, judge_configured, enabled):
        app = FastAPI()
        mount_evaluation(app, enabled)

        body = TestClient(app).get("/api/eval/health").text

        assert "not-a-real-key" not in body


# ── Switched off ────────────────────────────────────────────────────


class TestAbsentWhenDisabled:
    def test_the_routes_are_not_there(self, judge_configured, settings):
        app = FastAPI()
        mount_evaluation(app, settings)

        assert TestClient(app).get("/api/eval/health").status_code == 404

    def test_the_rest_of_the_api_is_untouched(self, judge_configured, settings):
        app = FastAPI()
        app.include_router(core_router)
        mount_evaluation(app, settings)

        # /config is the one core endpoint that needs no Qdrant and no hub.
        assert TestClient(app).get("/api/config").status_code == 200

    def test_a_missing_judge_is_not_an_error(self, monkeypatch, settings):
        """With the harness off, EvalSettings is never built, so a deployment
        that has no judge configured at all still starts."""
        for name in ("JUDGE_BASE_URL", "JUDGE_API_KEY", "JUDGE_MODEL"):
            monkeypatch.delenv(name, raising=False)
        get_eval_settings.cache_clear()

        mount_evaluation(FastAPI(), settings)  # does not raise

        get_eval_settings.cache_clear()

    def test_the_package_is_never_imported(self):
        """The property the `eval` extra rests on.

        A 404 would still be a 404 if main imported the package and declined to
        mount it, and then an image built without the extra would fail at
        import instead of booting. Checked in a subprocess because this one
        imports sentra.evaluation at the top, so sys.modules here proves
        nothing.
        """
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, sentra.main; print('sentra.evaluation' in sys.modules)",
            ],
            capture_output=True,
            text=True,
            cwd=BACKEND,
            env={**os.environ, "EVAL_ENABLED": "false"},
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False", "main imported the harness with it switched off"


# ── The judge has to be somebody else ───────────────────────────────


class TestJudgeIndependence:
    def test_boot_refuses_a_judge_that_is_the_chat_model(self, monkeypatch, enabled):
        monkeypatch.setenv("JUDGE_BASE_URL", JUDGE_HUB)
        monkeypatch.setenv("JUDGE_API_KEY", "not-a-real-key")
        monkeypatch.setenv("JUDGE_MODEL", enabled.chat_model)
        get_eval_settings.cache_clear()

        with pytest.raises(JudgeNotIndependent, match=enabled.chat_model):
            mount_evaluation(FastAPI(), enabled)

        get_eval_settings.cache_clear()

    def test_a_different_model_boots(self, judge_configured, enabled):
        mount_evaluation(FastAPI(), enabled)  # does not raise

    def test_nothing_is_mounted_when_it_refuses(self, monkeypatch, enabled):
        """A half-mounted harness would answer /health while being unusable."""
        monkeypatch.setenv("JUDGE_BASE_URL", JUDGE_HUB)
        monkeypatch.setenv("JUDGE_API_KEY", "not-a-real-key")
        monkeypatch.setenv("JUDGE_MODEL", enabled.chat_model)
        get_eval_settings.cache_clear()

        app = FastAPI()
        with pytest.raises(JudgeNotIndependent):
            mount_evaluation(app, enabled)

        assert TestClient(app).get("/api/eval/health").status_code == 404
        get_eval_settings.cache_clear()
