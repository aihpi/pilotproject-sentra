"""Registry tables.

The vocabulary is `docs/SOURCE_MANAGEMENT_NOTES.md`'s. Two tables, because a
document can carry several Aktenzeichen: 65 joint documents in this corpus name
133 between them, and `_FILENAME_RE.search()` keeps the first and drops 68. A
column could not hold that, and dropping them is what makes those documents
uncitable by two thirds of their identifiers.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentra.db import Base

# What a registry row can be. The set is deliberately small at this stage:
# this task observes the corpus and indexes nothing, so nothing here can reach
# `indexed` yet. The later values exist so the column does not have to be
# migrated the moment task 2 starts writing them.
PENDING = "pending"  # seen on disk, nothing done with it
NEEDS_REVIEW = "needs_review"  # something about it a human has to settle
INDEXED = "indexed"  # chunks in Qdrant, derived from this row
FAILED = "failed"  # parsing or embedding gave up
WITHDRAWN = "withdrawn"  # deliberately removed from the index, row kept

STATUS_VALUES = (PENDING, NEEDS_REVIEW, INDEXED, FAILED, WITHDRAWN)

# How the row got here.
FOLDER_IMPORT = "folder_import"
UPLOAD = "upload"

SOURCE_VALUES = (FOLDER_IMPORT, UPLOAD)


class Document(Base):
    """One file in the corpus.

    Identity is the content hash, not the filename. The notes measured why: 30
    filenames collide across the original folder tree, so a filename cannot be
    an identity, and `Ausarbeitungen/PE 6/` holds `EU 6-*` files, so neither can
    a path.
    """

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN " + str(STATUS_VALUES).replace('"', "'"), name="ck_documents_status"
        ),
        CheckConstraint(
            "source IN " + str(SOURCE_VALUES).replace('"', "'"), name="ck_documents_source"
        ),
        Index("ix_documents_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # sha256 of the bytes. Unique, so importing the same file twice — under two
    # names, from two folders — is one row and one document.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # Where the bytes are. Today a path relative to documents_dir, because the
    # files are on a mounted volume and this task moves nothing. Opaque on
    # purpose: a content-addressed store or S3 later is a change here and
    # nowhere else.
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)

    # What it was called when it arrived. Not identity, but it is what a person
    # recognises, and what Qdrant payloads currently key on.
    original_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=PENDING)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=FOLDER_IMPORT)

    # Why a human is being asked to look. Empty for a row nobody needs to.
    review_reason: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # The extension as found, lowercased. The corpus holds 23 .docx beside the
    # PDFs, which every glob in the codebase skips; recording them is how they
    # stop being invisible without deciding whether they belong.
    file_type: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    # What metadata.py could tell without parsing. Filled in properly when a
    # document is actually parsed; at this stage it is what the existing index
    # already knows, joined on original_name, so the registry is useful on day
    # one without hours of Docling.
    # Generously sized, because these arrive from extraction and extraction is
    # exactly what the registry exists to make correctable. The first scan hit
    # a `fachbereich` of 293 characters — five Fachbereich names run together
    # for a joint document, which is not a Fachbereich and is what a human has
    # to fix in task 5. A column too narrow to hold the wrong value would only
    # mean the registry could not record the problem.
    title: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    fachbereich: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    fachbereich_number: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    document_type: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    # Not a date column, deliberately. The index holds values like "WD 3 - 3000
    # - 164/21 und WD 9 - 3000 - 081/21 20. September 2021" — the extractor
    # swallowed the Aktenzeichen line of a joint document — and a date column
    # could only refuse them. The registry has to be able to hold the wrong
    # value in order to show it to somebody who can fix it; `validate` flags
    # anything that is not an ISO date.
    completion_date: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # Whether Qdrant currently holds chunks under this document's name. Recorded
    # rather than asked, so drift is a query rather than a round trip per row.
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    aktenzeichen: Mapped[list["DocumentAktenzeichen"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )
    files: Mapped[list["DocumentFile"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def is_filed_twice(self) -> bool:
        """The same bytes on disk under more than one name."""
        return len(self.files) > 1

    @property
    def primary_aktenzeichen(self) -> str:
        for entry in self.aktenzeichen:
            if entry.is_primary:
                return entry.aktenzeichen
        return ""


class DocumentFile(Base):
    """One file on disk holding this document's bytes.

    Normally exactly one. Four documents in this corpus are filed twice under
    different names — the same joint paper with its Aktenzeichen in a different
    order — and identity is the content hash, so those are one document with
    two files.

    Without this the registry could not say so. The scan would keep the first
    name, the second would look like a file with no row, and it would be
    indistinguishable from the genuinely orphaned documents in #140. Those two
    need different answers: one is a document to re-index, the other is a
    duplicate to remove from the corpus.
    """

    __tablename__ = "document_files"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_document_files_storage_key"),
        Index("ix_document_files_original_name", "original_name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)

    document: Mapped["Document"] = relationship(back_populates="files")


class DocumentAktenzeichen(Base):
    """One of a document's Aktenzeichen.

    Several rows per document is the normal case for a joint paper. `is_primary`
    marks the one a citation shows, which for a joint document is a choice
    rather than a fact — the first in the filename, until somebody says
    otherwise.
    """

    __tablename__ = "document_aktenzeichen"
    __table_args__ = (
        UniqueConstraint("document_id", "aktenzeichen", name="uq_document_aktenzeichen"),
        Index("ix_document_aktenzeichen_az", "aktenzeichen"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    aktenzeichen: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    document: Mapped[Document] = relationship(back_populates="aktenzeichen")
