"""The eval database: one engine, sessions on demand, and one failure class.

Nothing here connects at import. `create_engine` builds a pool lazily and opens
nothing until somebody asks for a connection, which is what lets
`mount_evaluation` run at startup without requiring Postgres to be up. SENTRA
serving documents and answers does not depend on the harness having a database,
and a deployment with the harness switched on but its database down still has
to answer everything else normally.

Schema lives in migrations, not in `Base.metadata.create_all`. A table created
by whichever process happened to boot first is a table nobody can review, and
the harness stores the yardstick that every verdict in a round is measured
against — see the immutability requirements on cases.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session

from sentra_eval.config import get_eval_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for every eval table. Alembic autogenerates from it."""


class EvalDatabaseUnavailable(RuntimeError):
    """The eval database could not be reached.

    Its own class rather than letting SQLAlchemyError through, because the two
    answer differently: this is a dependency being down, which is a 503 and
    nothing the caller did wrong. A broken query is a bug and stays a 500.

    main hands this class to the API error policy when it mounts the harness,
    so the policy stays in one place without api/ having to import evaluation —
    which would load the package even with EVAL_ENABLED off and undo the reason
    its dependencies are an extra.
    """


@lru_cache
def get_engine() -> Engine:
    """The engine, built once. Builds a pool; opens no connection."""
    settings = get_eval_settings()
    return create_engine(
        settings.eval_database_url,
        # A pooled connection that died while idle — a restarted Postgres, a
        # closed idle connection — is otherwise handed out and fails on use.
        # One round trip per checkout is cheap next to a generation call.
        pool_pre_ping=True,
    )


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session, committed on success and rolled back on anything else.

    The connection is acquired explicitly rather than left to the session,
    because that is what separates "the database is not there" from "the query
    was wrong" without having to guess from the exception.

    Sniffing the exception does not work, and was tried: a refused connection
    arrives as OperationalError with connection_invalidated False and
    is_disconnect False, which is indistinguishable from a deadlock by class.
    Acquisition is structural — nothing but reaching the server can fail here,
    and no query has run yet.

    So: failing to get a connection is EvalDatabaseUnavailable and a 503.
    Failing during the work is left alone and stays a 500, because a constraint
    violation is a bug and dressing it up as an outage would hide it. A
    connection that dies mid-use is unavailability again, and that one the pool
    does flag.
    """
    try:
        connection = get_engine().connect()
    except SQLAlchemyError as exc:
        raise EvalDatabaseUnavailable(str(exc)) from exc

    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        if getattr(exc, "connection_invalidated", False):
            raise EvalDatabaseUnavailable(str(exc)) from exc
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        connection.close()


def schema_revision() -> str | None:
    """The alembic revision the database is at, or None if it has none yet.

    Cheap enough for a health endpoint: one row from one small table. Being
    able to read this off a running instance is what makes "the database is up"
    a useful answer rather than half of one — up at the wrong revision is its
    own kind of down.
    """
    with session_scope() as session:
        row = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return str(row) if row is not None else None
