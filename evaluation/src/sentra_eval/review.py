"""Stufe 2: what a human has to look at, and what they decided.

Two things here are deliberate and both are about one number.

Section 6 of the Vorlage names the disagreement rate between the automatic
verdict and the human one as the most important measurement in the whole
process — it is what says whether the Stufe-1 threshold is set too loosely or
too strictly, which is the thing being calibrated. Everything else the harness
produces is in service of it.

So: **the queue does not carry machine verdicts.** Not "the screen hides
them" — they are not in the response. If they were, hiding them would be the
UI's choice, and one careless render would turn the headline metric into a
measure of anchoring without anyone noticing. A separate endpoint serves them,
and the review screen asks for it after the human has submitted.

And **a human verdict never overwrites a machine one.** Both rows are kept
forever. Overwriting would leave nothing to compare.
"""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sentra_eval import triage
from sentra_eval.models import (
    OK,
    STUFE_2,
    ZWECK_ANTWORT,
    Call,
    Case,
    CaseVersion,
    CheckResult,
    GroupCheckResult,
    Run,
    Verdict,
)


class ReviewError(RuntimeError):
    """A review operation the rules do not allow."""


class AlreadyAssessed(ReviewError):
    """This case already has a human verdict for this round.

    Rejected rather than versioned. A second verdict is almost always somebody
    re-submitting a form, not somebody changing their mind — and if it is the
    latter, the disagreement-rate metric needs to know which assessment was the
    first one, because that is the one Stufe 1 was being compared against.
    """


@dataclass
class QueueEntry:
    """One case awaiting a human, with everything needed to judge it.

    Deliberately without check results. See the module docstring.
    """

    test_id: str
    kategorie: str
    case_version_id: UUID
    version: int
    ausgangsfrage: str
    erwartete_antwort: str
    referenz_korrekt: str
    referenz_falsch: str
    grenzfall: bool
    gefunden_ueber: str
    calls: list[Call] = field(default_factory=list)
    # One sheet per case, so this is a fact about the case rather than a count
    # of how many of its answers somebody has got through.
    assessed: bool = False


def queue(session: Session, run_id: UUID) -> list[QueueEntry]:
    """The cases a human has to work through, and only those.

    Which ones is triage's decision: a Grenzfall always, anything a check or
    the judge flagged, and a seeded sample of the rest. A case that is clean
    and unsampled does not appear at all — that is the point of Stufe 1, and
    returning everything was Stufe 2 doing its job.
    """
    run = session.get(Run, run_id)
    if run is None:
        raise ReviewError(f"No run {run_id}")
    decisions = triage.by_case(session, run)
    rows = session.execute(
        select(Call, CaseVersion, Case)
        .join(CaseVersion, Call.case_version_id == CaseVersion.id)
        .join(Case, CaseVersion.case_id == Case.id)
        .where(Call.run_id == run_id, Call.zweck == ZWECK_ANTWORT, Call.status == OK)
        .order_by(Case.test_id, Call.variant_key, Call.repeat_index)
    ).all()

    assessed = {
        verdict.case_version_id
        for verdict in session.execute(select(Verdict).where(Verdict.run_id == run_id)).scalars()
    }

    entries: dict[UUID, QueueEntry] = {}
    for call, version, case in rows:
        decision = decisions.get(version.id)
        if decision is None or not decision.needs_review:
            continue
        entry = entries.get(version.id)
        if entry is None:
            entry = QueueEntry(
                test_id=case.test_id,
                kategorie=case.kategorie,
                case_version_id=version.id,
                version=version.version,
                ausgangsfrage=version.ausgangsfrage,
                erwartete_antwort=version.erwartete_antwort,
                referenz_korrekt=version.referenz_korrekt,
                referenz_falsch=version.referenz_falsch,
                grenzfall=version.grenzfall,
                # Why this case is in front of somebody: Stufe 2 because a
                # check flagged it, Stufe 3 because the sample drew it, or
                # Grenzfall because 4.4 never filters one.
                gefunden_ueber=decision.gefunden_ueber or STUFE_2,
            )
            entries[version.id] = entry
        entry.calls.append(call)
        entry.assessed = version.id in assessed

    return list(entries.values())


def machine_verdicts(
    session: Session, call_id: UUID
) -> tuple[list[CheckResult], list[GroupCheckResult]]:
    """What the checks said about a call, and about its group of repeats.

    Its own function, reached by its own endpoint, because the queue must not
    carry this. The review screen asks for it once the human has committed to
    an assessment.
    """
    call = session.get(Call, call_id)
    if call is None:
        raise ReviewError(f"No call {call_id}")

    per_call = list(
        session.execute(select(CheckResult).where(CheckResult.call_id == call_id)).scalars()
    )
    per_group = list(
        session.execute(
            select(GroupCheckResult).where(
                GroupCheckResult.run_id == call.run_id,
                GroupCheckResult.case_version_id == call.case_version_id,
                GroupCheckResult.variant_key == call.variant_key,
            )
        ).scalars()
    )
    return per_call, per_group


def record_verdict(
    session: Session,
    run_id: UUID,
    case_version_id: UUID,
    *,
    tester: str,
    kernbefunde: dict[str, str],
    quelle_4_3a: str,
    quelle_4_3b: str,
    quelle_4_3c: str,
    schweregrad: int,
    reproduzierbar: str,
    anmerkung: str = "",
) -> Verdict:
    """Store a human assessment of one case. Leaves every machine verdict alone.

    `gefunden_ueber` is derived here rather than taken from the caller. It says
    how the case reached a reviewer, which is half of what the trend report
    measures, and a client asserting it could misattribute a finding to the
    wrong Stufe without anyone noticing.
    """
    version = session.get(CaseVersion, case_version_id)
    if version is None:
        raise ReviewError(f"No case version {case_version_id}")
    if session.get(Run, run_id) is None:
        raise ReviewError(f"No run {run_id}")

    existing = session.execute(
        select(Verdict).where(Verdict.run_id == run_id, Verdict.case_version_id == case_version_id)
    ).scalar_one_or_none()
    if existing is not None:
        raise AlreadyAssessed(
            f"This case was already assessed by {existing.tester!r} in this round. The first "
            f"assessment is what Stufe 1 is measured against, so it is not replaced."
        )

    verdict = Verdict(
        run_id=run_id,
        case_version_id=case_version_id,
        tester=tester,
        gefunden_ueber=gefunden_ueber_for(session, run_id, version),
        kernbefunde=kernbefunde,
        quelle_4_3a=quelle_4_3a,
        quelle_4_3b=quelle_4_3b,
        quelle_4_3c=quelle_4_3c,
        schweregrad=schweregrad,
        reproduzierbar=reproduzierbar,
        anmerkung=anmerkung,
        # 3 and 4 go to KISZ regardless of which Stufe surfaced the case.
        kisz_meldung=schweregrad >= 3,
    )
    session.add(verdict)
    session.flush()
    return verdict


def gefunden_ueber_for(session: Session, run_id: UUID, version: CaseVersion) -> str:
    """How this case reached a reviewer, as triage decided.

    Derived rather than submitted: it is half of what the trend report
    measures, and a client asserting it could record a case as caught by
    Stufe 1 when the sample found it, which is the difference between "the
    threshold works" and "we got lucky".
    """
    run = session.get(Run, run_id)
    if run is None:
        raise ReviewError(f"No run {run_id}")
    decision = triage.by_case(session, run).get(version.id)
    return (decision.gefunden_ueber if decision else None) or STUFE_2


def kisz_escalations(session: Session, run_id: UUID) -> list[Verdict]:
    """Every verdict in the round that has to be reported to KISZ separately."""
    return list(
        session.execute(
            select(Verdict)
            .where(Verdict.run_id == run_id, Verdict.kisz_meldung.is_(True))
            .order_by(Verdict.schweregrad.desc())
        ).scalars()
    )
