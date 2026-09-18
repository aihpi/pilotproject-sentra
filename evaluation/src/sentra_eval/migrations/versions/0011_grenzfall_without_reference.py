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
    """An approved Grenzfall with no reference goes back to being a draft.

    The same shape as 0004, and for the same reason. The old constraint cannot
    describe those rows, so restoring it over them fails — which is a migration
    that cannot be undone once a single round has run, and that is what 0004
    was written to stop happening a second time.

    Returning them to entwurf is the least the older schema can hold: the old
    rule allows a draft to be incomplete, which is what a draft is for. It is
    still data loss — the approval and its timestamp go — and it is exactly the
    data the older schema had no way to represent.

    Reference-less Grenzfälle only exist above this revision, so on a database
    that never had one this is a no-op.
    """
    op.execute(
        "UPDATE case_versions SET status = 'entwurf', freigegeben_at = NULL "
        "WHERE status = 'freigegeben' AND grenzfall AND referenz_korrekt = ''"
    )

    op.drop_constraint(NAME, "case_versions", type_="check")
    op.create_check_constraint(NAME, "case_versions", OLD)
