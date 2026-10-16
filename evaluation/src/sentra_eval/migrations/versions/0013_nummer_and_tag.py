"""A permanent number and an editable tag for every case

The Test-ID ("TF-GO-014") did two jobs: it was the identity rounds and reports
pointed at, and a label carrying the category. A label must be correctable and
an identity must not change, so they are split (#285):

  nummer   a global running number, never changed and never reused
  tag      the old Test-ID for existing cases, kept as if set by hand so a
           later label change does not replace it (#300); clearing it hands
           the case to the generator

Existing cases are numbered in the order they were created, and keep their
Test-ID as their tag. The per-category counters become generic counters, so a
tag generated for a category continues where its Test-IDs stopped.

Revision ID: 0013_nummer_and_tag
Revises: 0012_varianten_aktiv
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_nummer_and_tag"
down_revision: str | None = "0012_varianten_aktiv"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NUMMER_COUNTER = "nummer"


def upgrade() -> None:
    op.rename_table("test_id_sequences", "counters")
    with op.batch_alter_table("counters") as batch:
        batch.alter_column(
            "kategorie", new_column_name="name", type_=sa.String(64), existing_nullable=False
        )

    op.drop_index("ix_cases_test_id", table_name="cases")
    with op.batch_alter_table("cases") as batch:
        batch.add_column(sa.Column("nummer", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("tag_manuell", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.alter_column(
            "test_id", new_column_name="tag", type_=sa.String(64), existing_nullable=False
        )

    bind = op.get_bind()
    ids = bind.execute(sa.text("SELECT id FROM cases ORDER BY created_at, tag")).scalars().all()
    for number, case_id in enumerate(ids, start=1):
        bind.execute(
            sa.text("UPDATE cases SET nummer = :n, tag_manuell = :manuell WHERE id = :id"),
            {"n": number, "manuell": True, "id": case_id},
        )
    bind.execute(
        sa.text("INSERT INTO counters (name, next_number) VALUES (:name, :n)"),
        {"name": NUMMER_COUNTER, "n": len(ids) + 1},
    )

    with op.batch_alter_table("cases") as batch:
        batch.alter_column("nummer", existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint("uq_cases_nummer", ["nummer"])
    op.create_index("ix_cases_tag", "cases", ["tag"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM counters WHERE name = :name"), {"name": NUMMER_COUNTER})
    op.drop_index("ix_cases_tag", table_name="cases")
    with op.batch_alter_table("cases") as batch:
        batch.drop_constraint("uq_cases_nummer", type_="unique")
        batch.drop_column("tag_manuell")
        batch.drop_column("nummer")
        batch.alter_column(
            "tag", new_column_name="test_id", type_=sa.String(32), existing_nullable=False
        )
    op.create_index("ix_cases_test_id", "cases", ["test_id"], unique=True)
    with op.batch_alter_table("counters") as batch:
        batch.alter_column(
            "name", new_column_name="kategorie", type_=sa.String(8), existing_nullable=False
        )
    op.rename_table("counters", "test_id_sequences")
