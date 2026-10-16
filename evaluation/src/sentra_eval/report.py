"""What a round produces: the Phase-4 sheets, and the number that calibrates the process.

Section 6 of the Vorlage names the disagreement between the automatic verdict
and the human one as "die wichtigste Kennzahl, um zu beurteilen, ob sich die
Prüfschwelle in Stufe 1 zu großzügig oder zu streng eingestellt ist".
Everything else in this harness exists to make that number computable.

Computing it means separating three outcomes, not counting findings:

    check fired, human agreed      the threshold is working here
    check fired, human disagreed   too strict — reviewer time spent for nothing
    check quiet, human found it    too lenient — this is what Stufe 3 is for

The second and third calibrate in opposite directions, so a single count of
findings tells you nothing about which way to move. That is the easy thing to
build by accident, and it is why this module counts pairs rather than events.

A case with no human verdict is none of the three. It is unassessed, and
counting it either way would move the headline number for a reason unrelated to
the threshold.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

import sentra_eval.triage as triage
from sentra_eval import checks
from sentra_eval import variants as variant_store
from sentra_eval.categories import KATEGORIE_NAMEN
from sentra_eval.models import (
    OK,
    QUELLE_FALSCH,
    ZWECK_ANTWORT,
    Call,
    Case,
    CaseVersion,
    CheckResult,
    GroupCheckResult,
    Run,
    Verdict,
)

# 4.3b is the pair that lines up directly: the check's verdict and the sheet's
# field use the same two words. Keeping the Vorlage's vocabulary everywhere,
# rather than inventing one, is what makes this comparison possible at all.
VERGLEICHBARE_PRUEFUNG = checks.QUELLENAUSWAHL

EINIG = "einig"
ZU_STRENG = "Stufe 1 zu streng"
ZU_GROSSZUEGIG = "Stufe 1 zu großzügig"
NICHT_BEWERTET = "nicht bewertet"


@dataclass
class Sheet:
    """One Phase-4 documentation sheet, section 6, field for field."""

    nummer: int
    tag: str
    datum: str
    tester: str
    kategorie: str
    angewendete_techniken: list[str]
    urspruenglicher_prompt: str
    geprüfte_varianten: list[str]
    varianten_erstellt_durch: str
    varianten_freigegeben_durch: str
    automatisiert_geprueft_durch: str
    ergebnis_automatikpruefung: str
    gefunden_ueber: str
    manuell_geprueft_durch: str
    kernbefund_je_variante: dict[str, str]
    quellenbewertung_4_3a: str
    quellenbewertung_4_3b: str
    quellenbewertung_4_3c: str
    schweregrad: int | None
    reproduzierbar: str
    freitext_anmerkung: str


def sheets(session: Session, run: Run) -> list[Sheet]:
    """Every case in the round as a Phase-4 sheet.

    Machine verdicts appear here even though the review queue withholds them:
    withhold while somebody is forming an assessment, include in the record
    afterwards. The sheet is what goes to KISZ, and a sheet that hid what the
    automation concluded would make the disagreement rate uncheckable.
    """
    decisions = triage.by_case(session, run)
    verdicts = {
        v.case_version_id: v
        for v in session.execute(select(Verdict).where(Verdict.run_id == run.id)).scalars()
    }

    rows = session.execute(
        select(CaseVersion, Case)
        .join(Case, CaseVersion.case_id == Case.id)
        .join(Call, Call.case_version_id == CaseVersion.id)
        .where(Call.run_id == run.id, Call.zweck == ZWECK_ANTWORT, Call.status == OK)
        .distinct()
    ).all()

    out: list[Sheet] = []
    for version, case in rows:
        decision = decisions.get(version.id)
        verdict = verdicts.get(version.id)
        machine = _machine_summary(session, run, version.id)
        variants = sorted({c.variant_key for c in _calls_for(session, run, version.id)})
        approved = variant_store.approved_for(session, version.id)

        out.append(
            Sheet(
                nummer=case.nummer,
                tag=case.tag,
                datum=run.started_at.date().isoformat(),
                tester=verdict.tester if verdict else "",
                kategorie=KATEGORIE_NAMEN.get(case.kategorie, case.kategorie),
                # 4.1 always; 4.2 once approved variants exist; 4.3 through the
                # source checks; 4.4 for a Grenzfall.
                angewendete_techniken=_techniques(run, version, variants),
                urspruenglicher_prompt=version.ausgangsfrage,
                geprüfte_varianten=variants,
                # Read off the variants rather than assumed: one written by
                # hand has a different provenance, and the sheet asks which.
                varianten_erstellt_durch=(
                    ", ".join(sorted({v.erstellt_durch for v in approved if v.erstellt_durch}))
                    or "entfällt"
                ),
                varianten_freigegeben_durch=(
                    ", ".join(
                        sorted({v.freigegeben_durch for v in approved if v.freigegeben_durch})
                    )
                    or "entfällt"
                ),
                automatisiert_geprueft_durch="Skript / LLM-Prüfmodell",
                ergebnis_automatikpruefung=machine,
                gefunden_ueber=(decision.gefunden_ueber if decision else "") or "nicht geprüft",
                manuell_geprueft_durch=verdict.tester if verdict else "entfällt",
                kernbefund_je_variante=verdict.kernbefunde if verdict else {},
                quellenbewertung_4_3a=verdict.quelle_4_3a if verdict else "",
                quellenbewertung_4_3b=verdict.quelle_4_3b if verdict else "",
                quellenbewertung_4_3c=verdict.quelle_4_3c if verdict else "",
                schweregrad=verdict.schweregrad if verdict else None,
                reproduzierbar=verdict.reproduzierbar if verdict else "",
                freitext_anmerkung=verdict.anmerkung if verdict else "",
            )
        )
    return sorted(out, key=lambda s: s.nummer)


def _calls_for(session: Session, run: Run, case_version_id: UUID) -> list[Call]:
    return list(
        session.execute(
            select(Call).where(
                Call.run_id == run.id,
                Call.case_version_id == case_version_id,
                Call.zweck == ZWECK_ANTWORT,
            )
        ).scalars()
    )


def _techniques(run: Run, version: CaseVersion, variants: list[str]) -> list[str]:
    techniques = []
    if run.repeats > 1:
        techniques.append("4.1 Wiederholungslauf")
    if len(variants) > 1:
        techniques.append("4.2 Prompt-Paraphrasierung")
    techniques.append("4.3 Quellenprüfung")
    if version.grenzfall:
        techniques.append("4.4 Grenzfall-Test")
    return techniques


def _machine_summary(session: Session, run: Run, case_version_id: UUID) -> str:
    """ "unauffällig" or "auffällig, siehe Anmerkung", as the sheet expects."""
    flagged = set()
    for result, _call in session.execute(
        select(CheckResult, Call)
        .join(Call, CheckResult.call_id == Call.id)
        .where(
            Call.run_id == run.id,
            Call.case_version_id == case_version_id,
            CheckResult.auffaellig.is_(True),
        )
    ).all():
        flagged.add(result.pruefung)
    for group in session.execute(
        select(GroupCheckResult).where(
            GroupCheckResult.run_id == run.id,
            GroupCheckResult.case_version_id == case_version_id,
            GroupCheckResult.auffaellig.is_(True),
        )
    ).scalars():
        flagged.add(group.pruefung)

    if not flagged:
        return "unauffällig"
    return f"auffällig, siehe Anmerkung ({', '.join(sorted(flagged))})"


# ── The number the process is calibrated by ─────────────────────────


@dataclass
class Agreement:
    """How often Stufe 1 and the human reached the same conclusion.

    Only `zu_streng` and `zu_grosszuegig` say anything about the threshold, and
    they say opposite things. `einig` is the denominator; `nicht_bewertet` is
    excluded from the rate entirely, because an unassessed case is not a
    disagreement.
    """

    einig: int = 0
    zu_streng: int = 0
    zu_grosszuegig: int = 0
    nicht_bewertet: int = 0

    @property
    def bewertet(self) -> int:
        return self.einig + self.zu_streng + self.zu_grosszuegig

    @property
    def abweichungsquote(self) -> float | None:
        """None rather than zero when nothing has been assessed.

        A round with no verdicts has no disagreement rate. Reporting 0.0 would
        read as perfect agreement, which is the most flattering possible lie
        about a threshold nobody has checked.
        """
        if self.bewertet == 0:
            return None
        return round((self.zu_streng + self.zu_grosszuegig) / self.bewertet, 4)


def agreement(session: Session, run: Run) -> Agreement:
    """Compare what the checks said with what the humans said, on 4.3b."""
    result = Agreement()
    for outcome in _agreement_by_case(session, run).values():
        _count(result, outcome)
    return result


def _count(result: Agreement, outcome: str) -> None:
    if outcome == EINIG:
        result.einig += 1
    elif outcome == ZU_STRENG:
        result.zu_streng += 1
    elif outcome == ZU_GROSSZUEGIG:
        result.zu_grosszuegig += 1
    else:
        result.nicht_bewertet += 1


def _agreement_by_case(session: Session, run: Run) -> dict[UUID, str]:
    """Each case version's outcome on 4.3b: einig, zu streng, zu großzügig or unassessed."""
    outcomes: dict[UUID, str] = {}
    verdicts = {
        v.case_version_id: v
        for v in session.execute(select(Verdict).where(Verdict.run_id == run.id)).scalars()
    }

    machine_by_case: dict[UUID, bool] = {}
    for check, call in session.execute(
        select(CheckResult, Call)
        .join(Call, CheckResult.call_id == Call.id)
        .where(Call.run_id == run.id, CheckResult.pruefung == VERGLEICHBARE_PRUEFUNG)
    ).all():
        # Any repeat citing the wrong source is the case citing the wrong
        # source, which is how a human reads it too.
        previous = machine_by_case.get(call.case_version_id, False)
        machine_by_case[call.case_version_id] = previous or check.auffaellig

    for case_version_id, machine_flagged in machine_by_case.items():
        verdict = verdicts.get(case_version_id)
        if verdict is None:
            outcomes[case_version_id] = NICHT_BEWERTET
            continue
        human_flagged = verdict.quelle_4_3b == QUELLE_FALSCH
        if machine_flagged == human_flagged:
            outcomes[case_version_id] = EINIG
        elif machine_flagged:
            # The check fired and the human did not agree: reviewer time spent
            # on something that was fine.
            outcomes[case_version_id] = ZU_STRENG
        else:
            # The human found what the check missed. This is what Stufe 3 is
            # for, and the direction that matters most.
            outcomes[case_version_id] = ZU_GROSSZUEGIG
    return outcomes


# ── Across rounds ───────────────────────────────────────────────────


@dataclass
class Trend:
    """The monthly Trendauswertung, section 6."""

    runden: int = 0
    faelle: int = 0
    nach_kategorie: dict[str, int] = field(default_factory=dict)
    schweregrade: dict[int, int] = field(default_factory=dict)
    kisz_meldungen: int = 0
    haeufigste_befunde: dict[str, int] = field(default_factory=dict)
    abweichung: dict[str, Any] = field(default_factory=dict)


def trend(session: Session) -> Trend:
    """Aggregate every round. Derived from stored rows, so it is reproducible."""
    runs = list(session.execute(select(Run)).scalars())
    out = Trend(runden=len(runs))

    kategorie: Counter[str] = Counter()
    schweregrad: Counter[int] = Counter()
    befunde: Counter[str] = Counter()
    combined = Agreement()

    for run in runs:
        found = agreement(session, run)
        combined.einig += found.einig
        combined.zu_streng += found.zu_streng
        combined.zu_grosszuegig += found.zu_grosszuegig
        combined.nicht_bewertet += found.nicht_bewertet

        for sheet in sheets(session, run):
            out.faelle += 1
            kategorie[sheet.kategorie] += 1
            if sheet.schweregrad is not None:
                schweregrad[sheet.schweregrad] += 1

    # Per case, not per call. A CheckResult is written for every call, so a
    # case flagged on all three of its repeats is one finding rather than
    # three — and counting the rows would scale this with `repeats`, which
    # makes two rounds run at different repeat counts incomparable. A trend
    # that cannot be compared across rounds is not a trend.
    #
    # It also keeps one denominator. Group checks are already recorded once per
    # case, so counting rows put per-call and per-case checks in the same table
    # with the per-call ones inflated by a factor of `repeats`.
    for check, _version_id in session.execute(
        select(CheckResult.pruefung, Call.case_version_id)
        .join(Call, CheckResult.call_id == Call.id)
        .where(CheckResult.auffaellig.is_(True))
        .distinct()
    ).all():
        befunde[check] += 1
    for check, _version_id in session.execute(
        select(GroupCheckResult.pruefung, GroupCheckResult.case_version_id)
        .where(GroupCheckResult.auffaellig.is_(True))
        .distinct()
    ).all():
        befunde[check] += 1

    out.nach_kategorie = dict(kategorie.most_common())
    out.schweregrade = dict(sorted(schweregrad.items()))
    out.haeufigste_befunde = dict(befunde.most_common())
    out.kisz_meldungen = len(
        session.execute(select(Verdict).where(Verdict.kisz_meldung.is_(True))).scalars().all()
    )
    out.abweichung = {
        "einig": combined.einig,
        "zu_streng": combined.zu_streng,
        "zu_grosszuegig": combined.zu_grosszuegig,
        "nicht_bewertet": combined.nicht_bewertet,
        "abweichungsquote": combined.abweichungsquote,
    }
    return out


# ── Broken down by label ────────────────────────────────────────────

# The labels a round can be broken down by (#289). See labels.py.
DIMENSIONEN: tuple[str, ...] = ("kategorie", "testart", "frageform", "herkunft")
OHNE_WERT = "(ohne)"


@dataclass
class BreakdownRow:
    """One combination of label values, across the rounds asked for."""

    werte: dict[str, str]
    faelle: int = 0
    auffaellig: int = 0
    befunde: dict[str, int] = field(default_factory=dict)
    abweichung: Agreement = field(default_factory=Agreement)


def breakdown(
    session: Session, dimensionen: list[str], *, run: Run | None = None
) -> list[BreakdownRow]:
    """Every case in a round, or in every round, grouped by one or more labels.

    A case counts once per round it was asked in. "auffaellig" is a case with
    at least one automatic finding, counted per case like the trend so the
    number does not scale with the repeats. The agreement is the same 4.3b
    comparison as the headline number, split by label.

    By the case's labels as they are now, not as they were when the round ran:
    labels are corrected after the fact, and a correction should re-sort the
    past rounds too, or the breakdown keeps the mistake.
    """
    unknown = [d for d in dimensionen if d not in DIMENSIONEN]
    if unknown or not dimensionen:
        raise ValueError(f"Aufschlüsseln geht nach {', '.join(DIMENSIONEN)}, nicht nach {unknown}.")

    runs = [run] if run is not None else list(session.execute(select(Run)).scalars())
    labels_of: dict[UUID, dict[str, str]] = {
        version_id: {d: getattr(case, d) or OHNE_WERT for d in dimensionen}
        for version_id, case in session.execute(
            select(CaseVersion.id, Case).join(Case, CaseVersion.case_id == Case.id)
        ).all()
    }

    rows: dict[tuple[str, ...], BreakdownRow] = {}

    def row_for(version_id: UUID) -> BreakdownRow:
        werte = labels_of[version_id]
        key = tuple(werte[d] for d in dimensionen)
        if key not in rows:
            rows[key] = BreakdownRow(werte=werte)
        return rows[key]

    for each in runs:
        asked = set(
            session.execute(
                select(Call.case_version_id)
                .where(Call.run_id == each.id, Call.zweck == ZWECK_ANTWORT)
                .distinct()
            ).scalars()
        )
        findings: dict[UUID, set[str]] = {version_id: set() for version_id in asked}
        for pruefung, version_id in session.execute(
            select(CheckResult.pruefung, Call.case_version_id)
            .join(Call, CheckResult.call_id == Call.id)
            .where(Call.run_id == each.id, CheckResult.auffaellig.is_(True))
            .distinct()
        ).all():
            findings.setdefault(version_id, set()).add(pruefung)
        for pruefung, version_id in session.execute(
            select(GroupCheckResult.pruefung, GroupCheckResult.case_version_id)
            .where(GroupCheckResult.run_id == each.id, GroupCheckResult.auffaellig.is_(True))
            .distinct()
        ).all():
            findings.setdefault(version_id, set()).add(pruefung)

        for version_id, found in findings.items():
            row = row_for(version_id)
            row.faelle += 1
            if found:
                row.auffaellig += 1
            for pruefung in found:
                row.befunde[pruefung] = row.befunde.get(pruefung, 0) + 1

        for version_id, outcome in _agreement_by_case(session, each).items():
            _count(row_for(version_id).abweichung, outcome)

    return sorted(rows.values(), key=lambda r: [r.werte[d] for d in dimensionen])
