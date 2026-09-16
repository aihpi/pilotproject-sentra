"""The schema comes from alembic, and only from alembic.

Needs a real Postgres, so it sits in the integration tier: the offline tier
covers the database being *un*reachable, which is the behaviour that has to
hold in CI, and this covers it being reachable.

Run it with the compose stack up:

    docker compose up -d eval-db
    uv run pytest tests/test_evaluation_migrations.py -m integration

It applies migrations to whatever EVAL_DATABASE_URL points at and leaves them
applied, the same way prepare_index leaves the test collections in place.
"""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from sentra.evaluation.config import get_eval_settings
from sentra.evaluation.db import Base, EvalDatabaseUnavailable, get_engine, schema_revision
from tests.conftest import BACKEND_DIR

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # alembic.ini holds a path relative to backend/, and pytest runs from
    # wherever it was invoked.
    config.set_main_option(
        "script_location", str(BACKEND_DIR / "src" / "sentra" / "evaluation" / "migrations")
    )
    return config


@pytest.fixture
def require_eval_db():
    """Skip when the database is absent. Fail for anything else.

    Catching bare Exception here was worse than no guard: with JUDGE_* unset,
    building the settings failed and the suite reported "the eval database is
    not reachable, start it with docker compose up -d eval-db" at somebody who
    had already started it. A guard that misnames the cause sends people to fix
    the wrong thing, which is the distinction #59 and #61 were both about.
    """
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except (EvalDatabaseUnavailable, SQLAlchemyError) as exc:
        pytest.skip(
            "The eval database is not reachable. Start it with:\n"
            "    docker compose up -d eval-db\n"
            f"({exc})"
        )


class TestMigrations:
    def test_upgrade_head_applies(self, require_eval_db, alembic_config):
        command.upgrade(alembic_config, "head")

        assert schema_revision() is not None

    def test_the_version_table_is_the_only_thing_the_baseline_creates(
        self, require_eval_db, alembic_config
    ):
        """The baseline creates no tables on purpose. The first real one
        arrives with the case store, on top of it."""
        command.upgrade(alembic_config, "head")

        tables = set(inspect(get_engine()).get_table_names())

        assert "alembic_version" in tables
        assert tables - {"alembic_version"} == set(), (
            "a migration created tables the baseline was not supposed to"
        )

    def test_nothing_creates_the_schema_behind_alembic(self, require_eval_db, alembic_config):
        """create_all would make the schema whatever the first process to boot
        decided, which is a schema nobody reviewed."""
        command.downgrade(alembic_config, "base")

        assert Base.metadata.tables == {}, (
            "models exist but no migration creates them — run alembic revision --autogenerate"
        )

        command.upgrade(alembic_config, "head")


class TestUnreachableIsStillItsOwnFailure:
    def test_schema_revision_raises_when_the_server_goes_away(self, require_eval_db, monkeypatch):
        """The offline tier proves this against a closed port; this proves the
        same class comes back when a real server was there and then was not."""
        monkeypatch.setenv("EVAL_DATABASE_URL", "postgresql+psycopg://sentra:sentra@127.0.0.1:1/x")
        # Both caches. get_eval_settings is lru_cached as well, so clearing only
        # the engine rebuilt it from the settings it had already memoised and
        # the test passed against the working database — it did not raise, and
        # it was right not to.
        get_eval_settings.cache_clear()
        get_engine.cache_clear()

        with pytest.raises(EvalDatabaseUnavailable):
            schema_revision()

        get_eval_settings.cache_clear()
        get_engine.cache_clear()
