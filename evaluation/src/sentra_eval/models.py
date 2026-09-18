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
# The three paraphrase styles 4.2 asks for. The keys are stored on calls and
# on Kernbefund entries, so they are part of two contracts and do not change
# casually.
VARIANTE_UMGANGSSPRACHLICH = "umgangssprachlich"
VARIANTE_FACHSPRACHLICH = "fachsprachlich"
VARIANTE_VERKUERZT = "verkuerzt"
VARIANTEN_STILE = (
    VARIANTE_UMGANGSSPRACHLICH,
    VARIANTE_FACHSPRACHLICH,
    VARIANTE_VERKUERZT,
)

# A proposed variant is not yet evidence. The Vorlage: "Freigegeben wird nur,
# was inhaltlich eindeutig dasselbe meint."
VORGESCHLAGEN = "vorgeschlagen"

ZWECK_ANTWORT = "antwort"
ZWECK_RECALL = "recall"

# ── Phase 4 of the Vorlage: the documentation sheet's vocabulary ────
#
# German, and exactly the Vorlage's wording. A Phase-4 sheet is generated from
# these, so storing anything else means translating twice — and a reviewer
# picking from a list that does not match the paper form has to translate in
# their head every time.

# 4.3a, Existenz- und Zitatprüfung
ZITAT_STIMMT = "existiert & stimmt überein"
ZITAT_WEICHT_AB = "weicht ab"
ZITAT_EXISTIERT_NICHT = "existiert nicht"
ZITAT_ENTFAELLT = "entfällt"

# 4.3b, Quellenauswahl
QUELLE_KORREKT = "korrekte Quelle"
QUELLE_FALSCH = "falsche bzw. veraltete Quelle"

# 4.3c, Kontextprüfung — human only, always
KONTEXT_STUETZT = "Quelle stützt Aussage"
KONTEXT_STUETZT_NICHT = "stützt Aussage nicht"

# Reproduzierbar?
REPRO_EINMALIG = "einmalig"
REPRO_WIEDERHOLT = "wiederholt"
REPRO_ENTFAELLT = "entfällt"

# Gefunden über
STUFE_2 = "Stufe 2 (auffällig markiert)"
STUFE_3 = "Stufe 3 (Stichprobe)"
GRENZFALL_IMMER = "Grenzfall (immer manuell, 4.4)"


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
        # answer measures nothing. Drafts may be incomplete — that is what a
        # draft is for.
        #
        # A Grenzfall is exempt from the reference, and has to be: it asks
        # something the corpus holds no document for, so there is no correct
        # source to name. Requiring one made 4.4 unreachable, since the runner
        # only plans approved versions (#130).
        CheckConstraint(
            "status = 'entwurf' OR ("
            "  erwartete_antwort <> ''"
            "  AND (grenzfall OR referenz_korrekt <> '')"
            "  AND freigegeben_at IS NOT NULL"
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

    # The feedback entry this case was drafted from, if any.
    #
    # Stored here rather than written back into feedback.jsonl: that file is an
    # append-only log written by SENTRA, and making it updatable in place is
    # the more expensive of the two changes. The id is derived from the
    # entry's timestamp and question, so it is stable for lines already
    # written and this is what stops the same complaint being imported twice.
    feedback_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)

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
    # Stufe 3's sample, fixed at the start of the round.
    #
    # Stored rather than drawn fresh so the sample can be recomputed months
    # later and shown to be what it claims. "Why was this case not reviewed"
    # then has an answer better than a shrug — which matters, because Stufe 3
    # exists to detect Stufe 1 systematically missing things, and a sample
    # nobody can reconstruct cannot support that claim.
    stichprobe_seed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The Vorlage leaves the rate open and suggests 10 percent as a starting
    # point. Stored on the run because changing it later must not change what a
    # finished round did.
    stichprobe_anteil: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)

    # Whether ragas scored this round. Off by default and stored, because it
    # roughly doubles a round's model calls — three LLM-scored metrics per
    # answer on top of the answer itself — and because a round scored with it
    # and a round scored without it are not the same evidence.
    ragas_aktiv: Mapped[bool] = mapped_column(nullable=False, default=False)

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


class GroupCheckResult(Base):
    """A verdict about a group of calls rather than about one of them.

    4.1 asks whether three answers to the same prompt differ, and 4.2 whether
    answers to three paraphrases do. Neither is a statement about any single
    call, and anchoring one to an arbitrary repeat would make it look like one
    — a reviewer reading "repeat 0: abweichend" would reasonably ask what was
    wrong with repeat 0, when the answer is nothing.

    The judge's verdicts land here too: it compares across repeats for exactly
    the same reason.
    """

    __tablename__ = "group_check_results"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "case_version_id",
            "variant_key",
            "pruefung",
            name="uq_group_check_results_one_per_check",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    case_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("case_versions.id", ondelete="RESTRICT"), index=True
    )
    variant_key: Mapped[str] = mapped_column(String(32), nullable=False, default=ORIGINAL)

    pruefung: Mapped[str] = mapped_column(String(48), nullable=False)
    ergebnis: Mapped[str] = mapped_column(String(48), nullable=False)
    auffaellig: Mapped[bool] = mapped_column(nullable=False, default=False)
    belege: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Verdict(Base):
    """A human's assessment of one test case in one round.

    Section 6 of the Vorlage is "Dokumentation **je Testfall**", and three of
    its fields say so rather than it being a matter of preference. `Reproduzierbar?
    einmalig / wiederholt / entfällt (nur ein Lauf vorhanden)` asks whether a
    finding recurred across the repeats, which no single answer can be asked.
    `Kernbefund je Variante` is a field inside one sheet, so the plural lives
    within the singular. And `Geprüfte Varianten (Wortlaut)` is plural on one
    sheet against one Ursprünglicher Prompt, one Schweregrad and one set of
    4.3a/b/c.

    Kept separately from CheckResult rather than updating it, and that is the
    point rather than tidiness. Section 6 names the disagreement rate between
    the automatic verdict and the human one as the most important number in the
    whole process: it is what says whether the Stufe-1 threshold is set too
    loosely or too strictly. A human verdict that overwrote the machine one
    would destroy the only input to that metric.
    """

    __tablename__ = "verdicts"
    __table_args__ = (
        UniqueConstraint("run_id", "case_version_id", name="uq_verdicts_one_per_case_per_run"),
        CheckConstraint("schweregrad BETWEEN 1 AND 4", name="ck_verdicts_schweregrad"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The version, not the case: what this assessment was made against has to
    # stay readable exactly as it was.
    case_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("case_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # There is no authentication anywhere in this project, so this is a name
    # somebody types. Required, because a finding nobody has to own is a
    # finding nobody follows up.
    tester: Mapped[str] = mapped_column(String(120), nullable=False)
    # Derived by the server, not submitted. Stufe 2 / Stufe 3 / Grenzfall is a
    # fact about how the case reached the reviewer; triage knows it and a
    # client asserting it could quietly misattribute how a finding was caught,
    # which is half of what the trend report measures.
    gefunden_ueber: Mapped[str] = mapped_column(String(48), nullable=False)

    # "Kernbefund je Variante": the finding for each answer, keyed
    # "<variant_key>#<repeat_index>" — "original#0", "original#1", and once 4.2
    # exists "umgangssprachlich#0" and so on. One field on the sheet, so one
    # field here, rather than a table of free text nothing will ever query.
    kernbefunde: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # 4.3a and 4.3b arrive prefilled from the machine checks and stay editable;
    # 4.3c is never prefilled, because whether a source actually supports a
    # claim is the fachliche Einschätzung the Vorlage keeps in human hands.
    quelle_4_3a: Mapped[str] = mapped_column(String(48), nullable=False)
    quelle_4_3b: Mapped[str] = mapped_column(String(48), nullable=False)
    quelle_4_3c: Mapped[str] = mapped_column(String(48), nullable=False)

    schweregrad: Mapped[int] = mapped_column(Integer, nullable=False)
    # Answerable now: it is a statement about the repeats, and this row is
    # about all of them.
    reproduzierbar: Mapped[str] = mapped_column(String(24), nullable=False)
    anmerkung: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Schweregrad 3 and 4 go to KISZ regardless of whether the case reached a
    # human through Stufe 2 or Stufe 3. Stored rather than derived on read so
    # that a round already reported cannot change its escalations if the rule
    # is ever adjusted.
    kisz_meldung: Mapped[bool] = mapped_column(nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Variant(Base):
    """One paraphrase of a case's Ausgangsfrage, per 4.2.

    Proposed by the judge model and then read by a human, because a variant
    that quietly asks a different question invalidates the robustness check it
    exists to run — the Vorlage requires that only what unambiguously means the
    same thing is approved.

    Attached to a case *version*, so approving one freezes it the same way the
    expected answer is frozen. Variants that changed between rounds would make
    the rounds incomparable, which is exactly what 4.2 measures.
    """

    __tablename__ = "variants"
    __table_args__ = (
        UniqueConstraint("case_version_id", "stil", name="uq_variants_one_per_style"),
        CheckConstraint(
            f"status IN ('{VORGESCHLAGEN}', '{FREIGEGEBEN}')", name="ck_variants_status"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("case_versions.id", ondelete="CASCADE"), index=True
    )
    # umgangssprachlich | fachsprachlich | verkuerzt. Also the variant_key on
    # any call made with it.
    stil: Mapped[str] = mapped_column(String(32), nullable=False)
    wortlaut: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=VORGESCHLAGEN)
    # "LLM (Erststellung)", for the Phase-4 sheet. Stored rather than assumed:
    # a variant somebody wrote by hand is a different provenance and the sheet
    # asks which it was.
    erstellt_durch: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    freigegeben_durch: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    freigegeben_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def is_approved(self) -> bool:
        return self.status == FREIGEGEBEN
