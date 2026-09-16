"""The eval tables.

The shape follows from one requirement in the Vorlage: the expected answer is
"formuliert bevor SENTRA getestet wird, damit die Erwartung nicht nachträglich
an die tatsächliche Ausgabe angepasst wird". A yardstick that can be adjusted
after seeing the measurement is not a yardstick, so this cannot be a matter of
people being careful — the schema has to make it true.

Hence the split:

  Case          the identity. A Test-ID, a category, and nothing that can be
                argued about later.
  CaseVersion   the content. Append-only once approved. Editing an approved
                version is not possible; you add another and approve that.

A draft is editable, because writing a case is iterative and nothing has been
measured against it yet. Approval is the moment it becomes evidence, and
`freigegeben_at` is what a later audit compares against a run's start.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentra.evaluation.db import Base

# Status values, German because the reviewer-facing vocabulary is German.
ENTWURF = "entwurf"
FREIGEGEBEN = "freigegeben"


class TestIdSequence(Base):
    """The next free number per category.

    A counter rather than max(number) + 1. The Vorlage requires that a number is
    never reused, "auch bei zurückgezogenen Testfällen nicht", and max + 1 hands
    the number back the moment the highest case is withdrawn or deleted. A
    counter cannot, whatever happens to the rows it counted.
    """

    __tablename__ = "test_id_sequences"

    kategorie: Mapped[str] = mapped_column(String(8), primary_key=True)
    next_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Case(Base):
    """A test case's identity. Its content is in its versions."""

    __tablename__ = "cases"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # "TF-GO-014". Unique across everything, allocated by TestIdSequence.
    test_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    kategorie: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Withdrawn rather than deleted. The number stays spent and the runs that
    # referenced it stay readable — a round that has been reported to KISZ
    # cannot acquire dangling references afterwards.
    zurueckgezogen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    versions: Mapped[list["CaseVersion"]] = relationship(
        back_populates="case", order_by="CaseVersion.version", cascade="all, delete-orphan"
    )


class CaseVersion(Base):
    """One version of a case's content. Immutable once approved.

    The field names are the Vorlage's, in German, deliberately. This table is
    what a Phase-4 documentation sheet is filled in from, and translating the
    vocabulary twice is how the two drift apart.
    """

    __tablename__ = "case_versions"
    __table_args__ = (
        UniqueConstraint("case_id", "version", name="uq_case_versions_case_version"),
        # An approved version is a yardstick, and a yardstick with no expected
        # answer or no correct reference measures nothing. Drafts may be
        # incomplete — that is what a draft is for.
        CheckConstraint(
            "status = 'entwurf' OR ("
            "  erwartete_antwort <> '' AND referenz_korrekt <> '' AND freigegeben_at IS NOT NULL"
            ")",
            name="ck_case_versions_approved_is_complete",
        ),
        CheckConstraint(
            f"status IN ('{ENTWURF}', '{FREIGEGEBEN}')",
            name="ck_case_versions_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ENTWURF)

    # ── The Vorlage's Phase 1 fields ────────────────────────────────
    ausgangsfrage: Mapped[str] = mapped_column(Text, nullable=False)
    abteilung: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    erwartete_antwort: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The source that actually supports the expected answer.
    referenz_korrekt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # A source on the same topic that is outdated or wrong. Optional, but it is
    # what makes 4.3b a real check rather than "did it cite anything": without
    # it there is no wrong answer for the model to reach for.
    referenz_falsch: Mapped[str] = mapped_column(Text, nullable=False, default="")
    grund_fuer_aufnahme: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 4.4. A Grenzfall is never filtered out of human review, so triage needs to
    # know before any check has run.
    grenzfall: Mapped[bool] = mapped_column(nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # The audit timestamp. A run may only use an approved version, so this
    # predating the run's start is what proves the expectation was written
    # before the answer it judges was seen.
    freigegeben_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    case: Mapped[Case] = relationship(back_populates="versions")

    @property
    def is_approved(self) -> bool:
        return self.status == FREIGEGEBEN
