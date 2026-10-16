"""variants opt-in on the run

Whether a round asks the approved variants (4.2) is chosen when it starts, like
the number of repeats (#266). Stored on the run for the same reason as
ragas_aktiv: a round asked with variants and one asked without are not the
same evidence. Existing rounds get false. Before #266 a round asked every
approved variant, so for those rounds the calls, not this flag, say whether
4.2 was applied; the report already reads it from the calls.

Revision ID: 0012_varianten_aktiv
Revises: 0011_grenzfall_without_reference
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_varianten_aktiv"
down_revision: str | None = "0011_grenzfall_without_reference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("varianten_aktiv", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("runs", "varianten_aktiv")
