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
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from sentra.api.routes import router as core_router
from sentra.evaluation import (
    EvalDatabaseUnavailable,
    MissingJudgeConfiguration,
    get_eval_settings,
)
from sentra.evaluation.db import get_engine, schema_revision, session_scope
from sentra.main import mount_evaluation

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
        monkeypatch.setenv("EVAL_DATABASE_URL", url)
        _clear_caches()

    _clear_caches()
    yield configure
    _clear_caches()


@pytest.fixture
def enabled(settings):
    return settings.model_copy(update={"eval_enabled": True})


@pytest.fixture
def app_with_harness(database_at, enabled):
    """A harness mounted against a database that is not there."""
    database_at(NOWHERE)
    app = FastAPI()
    app.include_router(core_router)
    mount_evaluation(app, enabled)
    return app


# ── Nothing connects until something asks ───────────────────────────


class TestLaziness:
    def test_building_the_engine_opens_no_connection(self, database_at):
        database_at(NOWHERE)

        engine = get_engine()

        assert engine.pool.checkedout() == 0

    def test_mounting_opens_no_connection(self, database_at, enabled):
        """The one that would make SENTRA's boot depend on Postgres. Mounting
        against a database that is not there has to succeed."""
        database_at(NOWHERE)

        mount_evaluation(FastAPI(), enabled)  # does not raise

        assert get_engine().pool.checkedout() == 0


# ── A database that is down is a 503, and only for eval ─────────────


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
        """The endpoint that has to work when the database does not."""
        response = TestClient(app_with_harness).get("/api/eval/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_reports_the_database_as_unavailable(self, app_with_harness):
        body = TestClient(app_with_harness).get("/api/eval/health").json()

        assert body["database"] == "unavailable"
        assert body["schema_revision"] is None

    def test_health_still_names_the_judge(self, app_with_harness):
        """Down database, mounted harness: the judge answer is still true."""
        body = TestClient(app_with_harness).get("/api/eval/health").json()

        assert body["judge_model"] == JUDGE_MODEL


class TestSentraIsUnaffected:
    def test_config_still_answers(self, app_with_harness):
        """The core endpoint that needs neither Qdrant nor the hub, so a
        failure here would be the eval database leaking into SENTRA."""
        assert TestClient(app_with_harness).get("/api/config").status_code == 200

    def test_the_error_handler_is_registered_only_with_the_harness(self, database_at, settings):
        """With EVAL_ENABLED off, nothing about the eval database is wired in —
        no handler, and the package is not imported to find out."""
        database_at(NOWHERE)
        app = FastAPI()
        mount_evaluation(app, settings)

        assert EvalDatabaseUnavailable not in app.exception_handlers

    def test_the_error_handler_is_registered_with_it(self, database_at, enabled):
        database_at(NOWHERE)
        app = FastAPI()
        mount_evaluation(app, enabled)

        assert EvalDatabaseUnavailable in app.exception_handlers


# ── The policy the handler applies ──────────────────────────────────


class TestTheGermanDetail:
    def test_a_raised_failure_becomes_a_503(self, database_at, enabled):
        """Proved through a route, because a handler that is registered but
        never reached is not a policy."""
        database_at(NOWHERE)
        app = FastAPI()
        mount_evaluation(app, enabled)

        @app.get("/api/eval/_probe")
        def probe() -> None:
            raise EvalDatabaseUnavailable("connection refused")

        response = TestClient(app, raise_server_exceptions=False).get("/api/eval/_probe")

        assert response.status_code == 503
        assert "Auswertung" in response.json()["detail"]


# ── The database does not need a judge ──────────────────────────────


class TestTheDatabaseIsNotTheJudge:
    """Regression. Both of these were broken when the judge settings were
    required rather than checked where they are used.

    Symptom: `alembic upgrade head` — a deployment step with nothing to do with
    a judge — failed with three missing pydantic fields, and the migration
    tests skipped with "the eval database is not reachable" at somebody whose
    database was running.
    """

    def test_the_engine_builds_with_no_judge_configured(self, monkeypatch):
        for name in ("JUDGE_BASE_URL", "JUDGE_API_KEY", "JUDGE_MODEL"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("EVAL_DATABASE_URL", NOWHERE)
        _clear_caches()

        assert get_engine() is not None  # no MissingJudgeConfiguration

        _clear_caches()

    def test_mounting_without_a_judge_says_which_values_are_missing(self, monkeypatch, enabled):
        """The harness still refuses to start without one — the requirement
        moved, it did not go away — and now names what is absent."""
        for name in ("JUDGE_BASE_URL", "JUDGE_API_KEY", "JUDGE_MODEL"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("EVAL_DATABASE_URL", NOWHERE)
        _clear_caches()

        with pytest.raises(MissingJudgeConfiguration) as caught:
            mount_evaluation(FastAPI(), enabled)

        message = str(caught.value)
        assert "JUDGE_BASE_URL" in message
        assert "JUDGE_MODEL" in message

        _clear_caches()

    def test_a_partial_judge_is_still_a_failure(self, monkeypatch, enabled):
        """Two of three set is the configuration mistake most likely to survive
        a review, so it fails naming only the one that is absent."""
        monkeypatch.setenv("JUDGE_BASE_URL", JUDGE_HUB)
        monkeypatch.setenv("JUDGE_MODEL", JUDGE_MODEL)
        monkeypatch.delenv("JUDGE_API_KEY", raising=False)
        monkeypatch.setenv("EVAL_DATABASE_URL", NOWHERE)
        _clear_caches()

        with pytest.raises(MissingJudgeConfiguration, match="JUDGE_API_KEY"):
            mount_evaluation(FastAPI(), enabled)

        _clear_caches()
