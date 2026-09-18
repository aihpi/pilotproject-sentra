"""The document registry: what the corpus consists of.

SENTRA's first migration. Until #141 there was no SQL schema at all — the
corpus was whatever happened to be in Qdrant, and nothing could notice the two
disagreeing, which is how 17 documents came to be searchable and citable with
no file behind them (#140).

Three tables, and the two beside `documents` are both there because identity is
the content hash rather than the filename:

  document_aktenzeichen   a joint paper carries several. 59 documents in this
                          corpus do, naming 64 Aktenzeichen that the ingestion
                          path drops, because it keeps the first match.
  document_files          the same bytes can sit on disk under more than one
                          name. Four documents here are filed twice, and
                          without this they would be indistinguishable from
                          documents that are simply missing.

Revision ID: 0001_document_registry
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_document_registry"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("original_name", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("review_reason", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("fachbereich", sa.String(length=1024), nullable=False),
        sa.Column("fachbereich_number", sa.String(length=256), nullable=False),
        sa.Column("document_type", sa.String(length=256), nullable=False),
        sa.Column("completion_date", sa.String(length=256), nullable=False),
        sa.Column("language", sa.String(length=64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('folder_import', 'upload')", name="ck_documents_source"),
        sa.CheckConstraint(
            "status IN ('pending', 'needs_review', 'indexed', 'failed', 'withdrawn')",
            name="ck_documents_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash"),
    )
    op.create_index(
        op.f("ix_documents_original_name"), "documents", ["original_name"], unique=False
    )
    op.create_index("ix_documents_status", "documents", ["status"], unique=False)
    op.create_table(
        "document_aktenzeichen",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("aktenzeichen", sa.String(length=64), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "aktenzeichen", name="uq_document_aktenzeichen"),
    )
    op.create_index(
        "ix_document_aktenzeichen_az", "document_aktenzeichen", ["aktenzeichen"], unique=False
    )
    op.create_index(
        op.f("ix_document_aktenzeichen_document_id"),
        "document_aktenzeichen",
        ["document_id"],
        unique=False,
    )
    op.create_table(
        "document_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("original_name", sa.String(length=512), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_document_files_storage_key"),
    )
    op.create_index(
        op.f("ix_document_files_document_id"), "document_files", ["document_id"], unique=False
    )
    op.create_index(
        "ix_document_files_original_name", "document_files", ["original_name"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_document_files_original_name", table_name="document_files")
    op.drop_index(op.f("ix_document_files_document_id"), table_name="document_files")
    op.drop_table("document_files")
    op.drop_index(op.f("ix_document_aktenzeichen_document_id"), table_name="document_aktenzeichen")
    op.drop_index("ix_document_aktenzeichen_az", table_name="document_aktenzeichen")
    op.drop_table("document_aktenzeichen")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index(op.f("ix_documents_original_name"), table_name="documents")
    op.drop_table("documents")
