"""The harness is its own application, and refuses to run next to itself.

It used to be a router mounted into SENTRA behind EVAL_ENABLED. That flag is
gone: whether the harness runs is decided by whether its process runs, which is
what independence means for something whose job is to measure SENTRA. A harness
that could not be restarted without restarting the thing it measures was not
independent, whatever its import graph said.

What still has to be true here (the SENTRA side of it — no routes, no import,
no settings — is asserted from SENTRA's own suite, since the harness has no
dependency on `sentra` to check it with):

  - the harness refuses to start when the judge resolves to the model under
    test. A round is about 180 generation calls, and finding out afterwards
    that every consistency verdict was SENTRA grading itself means discarding
    all of them.

Offline. The settings are read; no judge and no database are contacted.
"""

import pytest
from fastapi.testclient import TestClient

from sentra_eval import MissingJudgeConfiguration, get_eval_settings
from sentra_eval.app import create_app

JUDGE_HUB = "http://judge.invalid/v1"
JUDGE_MODEL = "a-judge-that-is-not-the-chat-model"


@pytest.fixture
def judge_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("JUDGE_BASE_URL", JUDGE_HUB)
    monkeypatch.setenv("JUDGE_API_KEY", "not-a-real-key")
    monkeypatch.setenv("JUDGE_MODEL", JUDGE_MODEL)
    monkeypatch.setenv("CHAT_MODEL_UNDER_TEST", "llama-3-3-70b")
    monkeypatch.setenv("EVAL_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'e.db'}")
    get_eval_settings.cache_clear()
    yield
    get_eval_settings.cache_clear()


# ── The harness is its own app ──────────────────────────────────────


class TestTheHarnessApp:
    def test_health_responds(self, judge_configured):
        with TestClient(create_app()) as client:
            response = client.get("/api/eval/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_says_which_judge_and_which_sentra(self, judge_configured):
        with TestClient(create_app()) as client:
            body = client.get("/api/eval/health").json()

        assert body["judge_model"] == JUDGE_MODEL
        assert body["sentra_base_url"]

    def test_health_does_not_leak_the_key(self, judge_configured):
        with TestClient(create_app()) as client:
            body = client.get("/api/eval/health").text

        assert "not-a-real-key" not in body

    def test_it_serves_nothing_of_sentras(self, judge_configured):
        """Two applications, not one split in half. The harness is a client of
        SENTRA over HTTP and serves none of its endpoints."""
        with TestClient(create_app()) as client:
            assert client.post("/api/explorer/answer", json={"query": "x"}).status_code == 404


# ── It will not start without an independent judge ──────────────────


class TestJudgeIndependence:
    def test_it_refuses_to_start_as_the_model_under_test(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JUDGE_BASE_URL", JUDGE_HUB)
        monkeypatch.setenv("JUDGE_API_KEY", "not-a-real-key")
        monkeypatch.setenv("JUDGE_MODEL", "llama-3-3-70b")
        monkeypatch.setenv("CHAT_MODEL_UNDER_TEST", "llama-3-3-70b")
        monkeypatch.setenv("EVAL_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'e.db'}")
        get_eval_settings.cache_clear()

        with pytest.raises(RuntimeError, match="llama-3-3-70b"), TestClient(create_app()):
            pass

        get_eval_settings.cache_clear()

    def test_it_refuses_to_start_with_no_judge_at_all(self, monkeypatch, tmp_path):
        for name in ("JUDGE_BASE_URL", "JUDGE_API_KEY", "JUDGE_MODEL"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("EVAL_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'e.db'}")
        get_eval_settings.cache_clear()

        with (
            pytest.raises(MissingJudgeConfiguration, match="JUDGE_MODEL"),
            TestClient(create_app()),
        ):
            pass

        get_eval_settings.cache_clear()

    def test_a_different_model_starts(self, judge_configured):
        with TestClient(create_app()) as client:
            assert client.get("/api/eval/health").status_code == 200
