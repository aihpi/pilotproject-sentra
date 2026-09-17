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

    test_id: str
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
                test_id=case.test_id,
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
    return sorted(out, key=lambda s: s.test_id)


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
            result.nicht_bewertet += 1
            continue
        human_flagged = verdict.quelle_4_3b == QUELLE_FALSCH
        if machine_flagged == human_flagged:
            result.einig += 1
        elif machine_flagged:
            # The check fired and the human did not agree: reviewer time spent
            # on something that was fine.
            result.zu_streng += 1
        else:
            # The human found what the check missed. This is what Stufe 3 is
            # for, and the direction that matters most.
            result.zu_grosszuegig += 1
    return result


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

    for (check,) in session.execute(
        select(CheckResult.pruefung).where(CheckResult.auffaellig.is_(True))
    ).all():
        befunde[check] += 1
    for (check,) in session.execute(
        select(GroupCheckResult.pruefung).where(GroupCheckResult.auffaellig.is_(True))
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
