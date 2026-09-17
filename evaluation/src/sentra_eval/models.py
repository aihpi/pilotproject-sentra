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

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentra_eval.db import Base

# Status values, German because the reviewer-facing vocabulary is German.
ENTWURF = "entwurf"
FREIGEGEBEN = "freigegeben"

# Run states.
LAUFEND = "laufend"
ABGESCHLOSSEN = "abgeschlossen"
FEHLGESCHLAGEN = "fehlgeschlagen"

# Call outcomes.
OK = "ok"
FEHLER = "fehler"

# The variant key for the unmodified Ausgangsfrage. Paraphrases (4.2) get their
# own keys when they exist; until then every call carries this one.
ORIGINAL = "original"

# What a call was made for. An answer is the thing under test; a recall probe
# asks the document search whether the expected source was findable at all, so
# that "the answer did not cite it" can be told apart from "retrieval never
# offered it".
ZWECK_ANTWORT = "antwort"
ZWECK_RECALL = "recall"


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

    # The same two sources as Aktenzeichen, which is what a check can match on.
    #
    # The Vorlage's reference fields hold citations a person reads — its worked
    # example is "GOBT § 35". SENTRA cites its own documents, by Aktenzeichen.
    # Comparing those two vocabularies compares nothing, so a case carries both:
    # the citation for the reviewer and the Aktenzeichen for the check.
    #
    # Empty is a real state, not an omission: a case about a legal question
    # SENTRA has no document for cannot be checked mechanically, and has to
    # report that rather than reporting a failure.
    referenz_korrekt_az: Mapped[str] = mapped_column(Text, nullable=False, default="")
    referenz_falsch_az: Mapped[str] = mapped_column(Text, nullable=False, default="")
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


class Run(Base):
    """One test round.

    Carries where it called and when it started, because a stored answer is
    only evidence if you can say what produced it. `started_at` is the other
    half of the audit property the case store set up: a call may only use an
    approved version, and that version's `freigegeben_at` has to precede this.
    """

    __tablename__ = "runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=LAUFEND)
    # Recorded rather than read from settings later: a round run against
    # staging and a round run against production are different evidence, and
    # the setting will have moved on by the time anybody asks.
    sentra_base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    # 4.1 asks for the same prompt three times in separate sessions. SENTRA
    # holds no session state, so that is three POSTs — but the number is stored
    # because a round that used a different one is not comparable.
    repeats: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    # Python-side, not server_default=func.now(), and this is load-bearing.
    # The audit property compares this against a version's freigegeben_at,
    # which is stamped in Python. Two clocks at two precisions make that
    # comparison quietly wrong: SQLite's CURRENT_TIMESTAMP truncates to the
    # second, so a run started milliseconds after an approval read as having
    # started before it, and on Postgres now() is transaction-start time, which
    # has the same effect for a different reason. One clock for both.
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fehler: Mapped[str] = mapped_column(Text, nullable=False, default="")

    calls: Mapped[list["Call"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Call(Base):
    """One request to SENTRA and what came back.

    There is exactly one row per planned call, which is what makes a round
    resumable: the rows *are* the progress record, so continuing means working
    out the plan again and skipping what is already there. A round is about 180
    generation calls at 20 to 29 seconds each, so losing 45 of them to a restart
    is an hour and a slice of hub quota.

    Request and response are stored whole. Every check in this feature is a
    pure function over one of these rows, which is what lets a round be
    re-checked later without calling SENTRA again — including with checks that
    did not exist when the round ran.
    """

    __tablename__ = "calls"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "case_version_id",
            "variant_key",
            "repeat_index",
            "zweck",
            name="uq_calls_planned_once",
        ),
        CheckConstraint(f"status IN ('{OK}', '{FEHLER}')", name="ck_calls_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    # The version, not the case. What a round measured against has to stay
    # readable exactly as it was, and a later draft must not change it.
    case_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("case_versions.id", ondelete="RESTRICT"), index=True
    )

    # "original", or the key of an approved paraphrase once 4.2 exists.
    variant_key: Mapped[str] = mapped_column(String(32), nullable=False, default=ORIGINAL)
    # 0, 1, 2 for the three repeats of 4.1.
    repeat_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    zweck: Mapped[str] = mapped_column(String(16), nullable=False, default=ZWECK_ANTWORT)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=OK)
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_body: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    response_body: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    http_status: Mapped[int | None] = mapped_column(Integer)
    # Wall time, not model time. What a reviewer waits for is the whole call.
    dauer_ms: Mapped[float | None] = mapped_column(Float)
    fehler: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="calls")
    case_version: Mapped[CaseVersion] = relationship()


class CheckResult(Base):
    """What one deterministic check said about one call.

    Structured rather than prose: check name, verdict, and the evidence behind
    it. The trend report aggregates these across rounds, and prose cannot be
    aggregated — "wo häufen sich Fußnotenfehler" is a group-by or it is a
    person reading every sheet again.

    Stored against the call rather than computed on read, because a round is
    evidence: what the check said at the time is part of the record, and a
    check whose thresholds changed later must not silently rewrite history.
    Re-running checks writes new rows for the same call and verdict name.
    """

    __tablename__ = "check_results"
    __table_args__ = (
        UniqueConstraint("call_id", "pruefung", name="uq_check_results_one_per_check"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    call_id: Mapped[UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)

    # Which check. "quellenauswahl" (4.3b), "retrieval_recall", and so on.
    pruefung: Mapped[str] = mapped_column(String(48), nullable=False)
    # The Vorlage's vocabulary where it has one, plus "nicht prüfbar".
    ergebnis: Mapped[str] = mapped_column(String(48), nullable=False)
    # True when this needs a human to look, which is what triage reads.
    auffaellig: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Whatever the verdict was based on: which sources were seen, what rank the
    # expected one was at. A verdict a reviewer cannot check is an assertion.
    belege: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    call: Mapped[Call] = relationship()
