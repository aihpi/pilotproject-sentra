"""Baseline: an empty schema the eval tables are added to.

Creates no tables. It exists so that the migration chain has a root and so that
`alembic upgrade head` is the only way anything gets created — the first table
arrives with the case store, on top of this.

An empty first revision is not ceremony. It puts alembic_version in the
database, which is what lets /api/eval/health answer "reachable, at revision X"
rather than just "reachable": a database at the wrong revision is its own kind
of unavailable, and the harness is where a schema that drifted would be
hardest to notice.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-16
"""

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
