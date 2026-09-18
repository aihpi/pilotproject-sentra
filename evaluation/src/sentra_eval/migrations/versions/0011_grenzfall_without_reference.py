"""Let an approved Grenzfall have no correct reference.

#130. The rule was enforced twice: in cases.approve and as a CHECK. Both
demanded referenz_korrekt on every approved version, including a Grenzfall —
a question the corpus holds no document for, which by construction has no
correct source to name. The runner only plans approved versions, so technique
4.4 could not run at all through the supported path.

The constraint is loosened, not dropped. An approved version still needs an
expected answer and a freigegeben_at, and an ordinary case still needs its
reference.

Revision ID: 0011_grenzfall_without_reference
Revises: 0010_ragas
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_grenzfall_without_reference"
down_revision: str | None = "0010_ragas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_case_versions_approved_is_complete"

OLD = (
    "status = 'entwurf' OR ("
    "  erwartete_antwort <> '' AND referenz_korrekt <> '' AND freigegeben_at IS NOT NULL"
    ")"
)

NEW = (
    "status = 'entwurf' OR ("
    "  erwartete_antwort <> ''"
    "  AND (grenzfall OR referenz_korrekt <> '')"
    "  AND freigegeben_at IS NOT NULL"
    ")"
)


def upgrade() -> None:
    op.drop_constraint(NAME, "case_versions", type_="check")
    op.create_check_constraint(NAME, "case_versions", NEW)


def downgrade() -> None:
    """Fails where an approved Grenzfall with no reference exists, which is the
    honest outcome: the old rule cannot describe those rows. Withdraw them
    first, or give them a reference, if the constraint really has to come back.
    """
    op.drop_constraint(NAME, "case_versions", type_="check")
    op.create_check_constraint(NAME, "case_versions", OLD)
