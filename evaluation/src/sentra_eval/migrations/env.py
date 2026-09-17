"""Alembic environment for the eval database.

The URL comes from EvalSettings rather than alembic.ini, so there is one answer
to "where is the eval database" and migrations cannot be run against a
different one than the application uses.
"""

from logging.config import fileConfig

from alembic import context

# Imported for its side effect: the models have to be loaded before
# Base.metadata knows about them, or `revision --autogenerate` cheerfully
# produces an empty migration and the schema silently stops being tracked.
# It worked by accident before this line — through router importing models —
# which is not something to leave a schema resting on.
from sentra_eval import models  # noqa: F401
from sentra_eval.config import get_eval_settings
from sentra_eval.db import Base, get_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate compares the database against this.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without connecting, for `alembic upgrade --sql`."""
    context.configure(
        url=get_eval_settings().eval_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against the database the application would use."""
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
