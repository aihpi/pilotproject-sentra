"""Labels on the case: Testart, Frageform, Herkunft

The Kategorie stays where it was and becomes one of four labels (#286). The
three new ones are filled for existing cases from what is already known:

  herkunft    "Prüfer-Vorlage" where grund_fuer_aufnahme says so, "Feedback"
              where the case came from a feedback entry, "manuell" otherwise
  frageform   "allgemein"/"konkret" from the reviewer note "(MS05, Konkret)"
  testart     "Grenzfall · außerhalb des Bestands" where the latest version is
              a Grenzfall, empty otherwise; nobody has said yet what an
              ordinary case is meant to test

Revision ID: 0014_case_labels
Revises: 0013_nummer_and_tag
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_case_labels"
down_revision: str | None = "0013_nummer_and_tag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.add_column(sa.Column("testart", sa.String(64), nullable=False, server_default=""))
        batch.add_column(sa.Column("frageform", sa.String(16), nullable=False, server_default=""))
        batch.add_column(sa.Column("herkunft", sa.String(64), nullable=False, server_default=""))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT c.id, v.grund_fuer_aufnahme, v.feedback_id, v.grenzfall "
            "FROM cases c JOIN case_versions v ON v.case_id = c.id "
            "WHERE v.version = (SELECT max(version) FROM case_versions w WHERE w.case_id = c.id)"
        )
    ).all()
    for case_id, grund, feedback_id, grenzfall in rows:
        grund = grund or ""
        if grund.startswith("Prüfer-Vorlage"):
            herkunft = "Prüfer-Vorlage"
        elif feedback_id:
            herkunft = "Feedback"
        else:
            herkunft = "manuell"
        lowered = grund.lower()
        frageform = (
            "konkret" if "konkret)" in lowered else "allgemein" if "allgemein)" in lowered else ""
        )
        testart = "Grenzfall · außerhalb des Bestands" if grenzfall else ""
        bind.execute(
            sa.text("UPDATE cases SET herkunft = :h, frageform = :f, testart = :t WHERE id = :id"),
            {"h": herkunft, "f": frageform, "t": testart, "id": case_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.drop_column("herkunft")
        batch.drop_column("frageform")
        batch.drop_column("testart")
