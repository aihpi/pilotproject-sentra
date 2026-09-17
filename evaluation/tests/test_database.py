"""The eval database is a dependency of the harness, not of SENTRA.

Three properties, in the order they would hurt if they broke:

  - nothing connects at import or at mount. If it did, SENTRA's boot would
    depend on Postgres being up, and the harness is meant to be optional even
    when it is switched on.
  - the harness answering "my database is down" does not stop SENTRA answering
    questions. /api/explorer and /api/documents have nothing to do with it.
  - /api/eval/health keeps answering while the database is down, and says so.
    Every other eval route 503s. "Is the harness mounted" and "is its database
    reachable" are different questions and need different answers.

Offline. The unreachable database is a real connection attempt against a closed
port on localhost, which is refused immediately — no Postgres, no waiting, and
a genuine driver failure rather than a mocked one. Applying migrations needs a
real server and lives in the integration tier.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from sentra_eval import (
    EvalDatabaseUnavailable,
    MissingJudgeConfiguration,
    get_eval_settings,
)
from sentra_eval.app import create_app
from sentra_eval.db import get_engine, schema_revision, session_scope

# Nothing listens on 1. A connection there is refused by the kernel at once,
# which is what keeps this offline and fast.
NOWHERE = "postgresql+psycopg://sentra:sentra@127.0.0.1:1/sentra_eval"

JUDGE_HUB = "http://judge.invalid/v1"
JUDGE_MODEL = "a-judge-that-is-not-the-chat-model"


def _clear_caches() -> None:
    get_eval_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture
def database_at(monkeypatch):
    """Point the harness at a given database URL, caches cleared around it."""

    def configure(url: str):
        monkeypatch.setenv("JUDGE_BASE_URL", JUDGE_HUB)
        monkeypatch.setenv("JUDGE_API_KEY", "not-a-real-key")
        monkeypatch.setenv("JUDGE_MODEL", JUDGE_MODEL)
        monkeypatch.setenv("CHAT_MODEL_UNDER_TEST", "llama-3-3-70b")
        monkeypatch.setenv("EVAL_DATABASE_URL", url)
        _clear_caches()

    _clear_caches()
    yield configure
    _clear_caches()


@pytest.fixture
def app_with_harness(database_at):
    """The harness running against a database that is not there."""
    database_at(NOWHERE)
    return create_app()


# ── Nothing connects until something asks ───────────────────────────


class TestLaziness:
    def test_building_the_engine_opens_no_connection(self, database_at):
        database_at(NOWHERE)

        engine = get_engine()

        assert engine.pool.checkedout() == 0

    def test_starting_the_harness_opens_no_connection(self, database_at):
        """The harness has to come up and report the problem through health,
        rather than crash-loop while somebody is trying to find out what is
        wrong."""
        database_at(NOWHERE)

        with TestClient(create_app()) as client:
            assert client.get("/api/eval/health").status_code == 200

        assert get_engine().pool.checkedout() == 0


# ── A database that is down is a 503, and only for the harness ──────


class TestUnreachableDatabase:
    def test_session_scope_raises_our_own_class(self, database_at):
        database_at(NOWHERE)

        with pytest.raises(EvalDatabaseUnavailable), session_scope() as session:
            session.execute(text("SELECT 1"))

    def test_schema_revision_raises_rather_than_guessing(self, database_at):
        database_at(NOWHERE)

        with pytest.raises(EvalDatabaseUnavailable):
            schema_revision()

    def test_health_still_answers(self, app_with_harness):
        with TestClient(app_with_harness) as client:
            response = client.get("/api/eval/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_reports_the_database_as_unavailable(self, app_with_harness):
        with TestClient(app_with_harness) as client:
            body = client.get("/api/eval/health").json()

        assert body["database"] == "unavailable"
        assert body["schema_revision"] is None

    def test_a_case_route_answers_503_in_german(self, database_at):
        """The policy the harness now owns itself. It used to be registered
        from api/errors.py with the exception class passed in, because `api`
        importing the harness would have loaded it into every SENTRA process.
        Separate applications make that unnecessary."""
        database_at(NOWHERE)

        with TestClient(create_app()) as client:
            response = client.get("/api/eval/cases")

        assert response.status_code == 503
        assert "Auswertung" in response.json()["detail"]


# ── The database does not need a judge ──────────────────────────────


class TestTheDatabaseIsNotTheJudge:
    """Regression. Both of these were broken when the judge settings were
    required rather than checked where they are used: `alembic upgrade head`,
    a deployment step with nothing to do with a judge, failed with three
    missing pydantic fields.
    """

    def test_the_engine_builds_with_no_judge_configured(self, monkeypatch):
        for name in ("JUDGE_BASE_URL", "JUDGE_API_KEY", "JUDGE_MODEL"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("EVAL_DATABASE_URL", NOWHERE)
        _clear_caches()

        assert get_engine() is not None  # no MissingJudgeConfiguration

        _clear_caches()

    def test_starting_the_app_without_a_judge_says_what_is_missing(self, monkeypatch):
        """The requirement moved to startup, it did not go away."""
        for name in ("JUDGE_BASE_URL", "JUDGE_API_KEY", "JUDGE_MODEL"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("EVAL_DATABASE_URL", NOWHERE)
        _clear_caches()

        with pytest.raises(MissingJudgeConfiguration) as caught, TestClient(create_app()):
            pass

        assert "JUDGE_BASE_URL" in str(caught.value)
        assert "JUDGE_MODEL" in str(caught.value)

        _clear_caches()

    def test_a_partial_judge_is_still_a_failure(self, monkeypatch):
        """Two of three set is the mistake most likely to survive a review."""
        monkeypatch.setenv("JUDGE_BASE_URL", JUDGE_HUB)
        monkeypatch.setenv("JUDGE_MODEL", JUDGE_MODEL)
        monkeypatch.delenv("JUDGE_API_KEY", raising=False)
        monkeypatch.setenv("EVAL_DATABASE_URL", NOWHERE)
        _clear_caches()

        with (
            pytest.raises(MissingJudgeConfiguration, match="JUDGE_API_KEY"),
            TestClient(create_app()),
        ):
            pass

        _clear_caches()
