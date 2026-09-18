"""Users that can be administered, rather than only configured.

Until now a user existed only in SENTRA_USERS, which made adding a colleague a
deployment: hash a password on a developer's machine, edit a sealed secret,
restart. Nobody does that for the third reviewer, so the pilot ends up sharing
logins — which destroys the one thing the login was for, an author on a
verdict.

Configuration keeps working as a bootstrap. It is how the first admin exists
before anybody can sign in to create one, and a row here wins over a configured
name so that a password changed in the UI is not undone by the environment.

The hash column holds the same scrypt.<salt>.<key> the login already verifies,
so a configured user and an administered one are checked by one verifier.

Revision ID: 0002_users
Revises: 0001_document_registry
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_users"
down_revision: str | None = "0001_document_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("users")
