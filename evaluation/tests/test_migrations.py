"""The schema comes from alembic, and only from alembic.

Needs a real Postgres, so it sits in the integration tier: the offline tier
covers the database being *un*reachable, which is the behaviour that has to
hold in CI, and this covers it being reachable.

Run it with the compose stack up:

    docker compose --profile eval up -d eval-db
    cd evaluation && uv run pytest tests/test_migrations.py -m integration

It applies migrations to whatever EVAL_DATABASE_URL points at and leaves them
applied, the same way prepare_index leaves the test collections in place.
"""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from sentra_eval.config import get_eval_settings
from sentra_eval.db import Base, EvalDatabaseUnavailable, get_engine, schema_revision
from tests.conftest import EVALUATION_DIR

pytestmark = pytest.mark.integration

# Tables whose contents are somebody's work rather than schema. `cases` alone
# would not do: a database can hold a finished round whose cases were withdrawn.
_WORK_TABLES = ("cases", "runs", "verdicts")


def _refuse_a_populated_database() -> None:
    """Skip, with the reason, rather than dropping a round somebody needs."""
    engine = get_engine()
    present = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        for table in _WORK_TABLES:
            if table not in present:
                continue
            count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0
            if count:
                pytest.skip(
                    f"The eval database holds {count} row(s) in {table}. Downgrading "
                    "to base would drop them. Point EVAL_DATABASE_URL at a scratch "
                    "database to run this."
                )


@pytest.fixture(scope="module")
def alembic_config() -> Config:
    config = Config(str(EVALUATION_DIR / "alembic.ini"))
    # alembic.ini holds a path relative to backend/, and pytest runs from
    # wherever it was invoked.
    config.set_main_option(
        "script_location", str(EVALUATION_DIR / "src" / "sentra_eval" / "migrations")
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

    def test_the_schema_matches_the_models(self, require_eval_db, alembic_config):
        """The check worth having, and the one that keeps working as tables are
        added: after upgrading, alembic finds nothing left to generate.

        This replaces a pair of assertions that the baseline creates no tables.
        Those were true while the baseline was the head and became false the
        moment the case store landed — they described a moment rather than a
        rule. A model changed without a migration is the failure that actually
        happens, and it is what this catches.
        """
        command.upgrade(alembic_config, "head")

        with get_engine().connect() as connection:
            context = MigrationContext.configure(connection)
            differences = compare_metadata(context, Base.metadata)

        assert differences == [], (
            "the models and the database disagree — run:\n"
            "    uv run alembic revision --autogenerate -m '...'\n"
            f"{differences}"
        )

    def test_every_model_table_exists(self, require_eval_db, alembic_config):
        command.upgrade(alembic_config, "head")

        tables = set(inspect(get_engine()).get_table_names())

        assert "alembic_version" in tables
        assert set(Base.metadata.tables) <= tables

    def test_downgrading_to_base_removes_them_again(self, require_eval_db, alembic_config):
        """A migration that cannot be undone is one nobody can test twice.

        Skips rather than runs where the database holds work (#144). Downgrading
        to base drops every table, and a round is over an hour of wall clock and
        a slice of hub quota — while the human verdicts in it cannot be
        regenerated by re-running anything at all, which is what makes the
        disagreement rate the one number a rebuild cannot recover.

        `-m integration` says "I have the services"; it does not say "and this
        database is scratch". CI gets an empty one, so this still runs where it
        is meant to.
        """
        _refuse_a_populated_database()

        command.downgrade(alembic_config, "base")

        tables = set(inspect(get_engine()).get_table_names())
        assert set(Base.metadata.tables) & tables == set()

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
