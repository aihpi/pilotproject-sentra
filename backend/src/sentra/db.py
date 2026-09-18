"""SENTRA's registry database: one engine, sessions on demand, one failure class.

SENTRA had no SQL database until now. Qdrant held the corpus, and what the
corpus *contained* was whatever happened to be in Qdrant — which is how 17
documents came to be searchable and citable with no file behind them (#140),
with nothing in the system able to notice.

The registry is the answer to "what does the corpus consist of", and Qdrant
becomes derived from it. That ordering is the whole design in
docs/SOURCE_MANAGEMENT_NOTES.md.

Nothing here connects at import. `create_engine` builds a pool lazily and opens
nothing until somebody asks for a connection, so a deployment whose registry
database is down still answers questions and serves documents. Retrieval does
not read this database.

Schema lives in migrations, not in `Base.metadata.create_all`. A table created
by whichever process booted first is a table nobody reviewed.

This deliberately mirrors the evaluation harness's own database module rather
than sharing it. The harness is a separate distribution with its own database,
and the registry is SENTRA's own — docs/SOURCE_MANAGEMENT_NOTES.md predates
that split and says "Postgres (already coming for eval)", which would re-couple
the two and put SENTRA's ability to start in the harness's hands.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session

from sentra.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for every registry table. Alembic autogenerates from it."""


class RegistryDatabaseUnavailable(RuntimeError):
    """The registry database could not be reached.

    Its own class rather than letting SQLAlchemyError through, because the two
    answer differently: this is a dependency being down, which is a 503 and
    nothing the caller did wrong. A broken query is a bug and stays a 500.
    """


@lru_cache
def get_engine() -> Engine:
    """The engine, built once. Builds a pool; opens no connection."""
    settings = get_settings()
    return create_engine(settings.registry_database_url, pool_pre_ping=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session, committed on success and rolled back on anything else.

    The connection is acquired explicitly rather than left to the session,
    because that is what separates "the database is not there" from "the query
    was wrong" without guessing from the exception class. A refused connection
    arrives as OperationalError with `is_disconnect` False, which is
    indistinguishable from a deadlock by class alone; acquisition is
    structural, since nothing but reaching the server can fail there.
    """
    try:
        connection = get_engine().connect()
    except SQLAlchemyError as exc:
        raise RegistryDatabaseUnavailable(str(exc)) from exc

    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        if getattr(exc, "connection_invalidated", False):
            raise RegistryDatabaseUnavailable(str(exc)) from exc
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        connection.close()


def schema_revision() -> str | None:
    """The alembic revision the database is at, or None if it has none yet."""
    with session_scope() as session:
        row = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return str(row) if row is not None else None
