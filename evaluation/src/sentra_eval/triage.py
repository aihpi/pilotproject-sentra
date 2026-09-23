"""Stufe 1's decision: which cases a human actually has to look at.

The Vorlage's three stages only pay off if this filters. Until this existed the
queue was every case in the round, which is Stufe 2 doing Stufe 1's job.

    Grenzfall            → review, always, never filtered   (4.4)
    any check auffällig  → review                            (Stufe 2)
    judge auffällig      → review                            (Stufe 2)
    otherwise            → pool → seeded sample → review     (Stufe 3)

Stufe 3 is the part that is easy to get wrong by making it convenient. Its
purpose is to detect Stufe 1 systematically missing things, which only works if
the sample is drawn without regard to what Stufe 1 concluded — so it is a
seeded shuffle of the unflagged pool and nothing cleverer. The seed lives on the
run, so the sample can be recomputed later and shown to be what it claims.
"""

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sentra_eval.models import (
    GRENZFALL_IMMER,
    OK,
    STUFE_2,
    STUFE_3,
    ZWECK_ANTWORT,
    Call,
    CaseVersion,
    CheckResult,
    GroupCheckResult,
    Run,
)


@dataclass(frozen=True)
class Triage:
    """Why a case is, or is not, in front of a human."""

    case_version_id: UUID
    gefunden_ueber: str | None
    auffaellige_pruefungen: tuple[str, ...]

    @property
    def needs_review(self) -> bool:
        return self.gefunden_ueber is not None


def _sample_rank(seed: int, case_version_id: UUID) -> int:
    """A stable pseudo-random ordering of the unflagged pool.

    Hashing the seed with the case id rather than shuffling a list, so the
    answer does not depend on how many cases were in the round or what order
    they came back in. A case's position is a fact about the case and the seed,
    which is what makes it reproducible.
    """
    digest = hashlib.sha256(f"{seed}:{case_version_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def triage_run(session: Session, run: Run) -> list[Triage]:
    """Decide every case in the round."""
    versions = list(
        session.execute(
            select(CaseVersion)
            .join(Call, Call.case_version_id == CaseVersion.id)
            .where(Call.run_id == run.id, Call.zweck == ZWECK_ANTWORT, Call.status == OK)
            .distinct()
        ).scalars()
    )

    flagged: dict[UUID, set[str]] = {}
    for result, call in session.execute(
        select(CheckResult, Call)
        .join(Call, CheckResult.call_id == Call.id)
        .where(Call.run_id == run.id, CheckResult.auffaellig.is_(True))
    ).all():
        flagged.setdefault(call.case_version_id, set()).add(result.pruefung)

    for group in session.execute(
        select(GroupCheckResult).where(
            GroupCheckResult.run_id == run.id, GroupCheckResult.auffaellig.is_(True)
        )
    ).scalars():
        flagged.setdefault(group.case_version_id, set()).add(group.pruefung)

    decided: list[Triage] = []
    pool: list[CaseVersion] = []
    for version in versions:
        reasons = tuple(sorted(flagged.get(version.id, ())))
        if version.grenzfall:
            # 4.4 first, and before the flags: a Grenzfall reaching a human
            # because a check fired would be recorded as Stufe 2, when the
            # truth is that it was never eligible for filtering.
            decided.append(Triage(version.id, GRENZFALL_IMMER, reasons))
        elif reasons:
            decided.append(Triage(version.id, STUFE_2, reasons))
        else:
            pool.append(version)

    # Stufe 3. Drawn from the unflagged pool only, because its job is to find
    # what Stufe 1 missed — sampling cases Stufe 1 already caught would measure
    # nothing. Grenzfälle are not here either: they are never unflagged.
    wanted = round(len(pool) * run.stichprobe_anteil)
    ranked = sorted(pool, key=lambda v: _sample_rank(run.stichprobe_seed, v.id))
    sampled = {v.id for v in ranked[:wanted]}

    for version in pool:
        decided.append(Triage(version.id, STUFE_3 if version.id in sampled else None, ()))

    return decided


def by_case(session: Session, run: Run) -> dict[UUID, Triage]:
    return {t.case_version_id: t for t in triage_run(session, run)}
