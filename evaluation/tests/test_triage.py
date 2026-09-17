"""Stufe 1's decision: who a human actually has to look at.

The three stages only pay off if this filters. Before it existed the queue was
every case in the round, which is Stufe 2 doing Stufe 1's job.

The rules, in order, and the order matters:

    Grenzfall            → review, always, never filtered   (4.4)
    any check auffällig  → review                            (Stufe 2)
    judge auffällig      → review                            (Stufe 2)
    otherwise            → pool → seeded sample → review     (Stufe 3)

Stufe 3 is the one that is easy to spoil by making it convenient. Its purpose
is to detect Stufe 1 systematically missing things, which only works if the
sample is drawn without regard to what Stufe 1 concluded, and if it can be
reconstructed afterwards. A sample nobody can reproduce cannot support the
claim it exists to make.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sentra_eval import cases as case_store
from sentra_eval import triage
from sentra_eval.categories import Kategorie
from sentra_eval.db import Base
from sentra_eval.models import (
    GRENZFALL_IMMER,
    OK,
    STUFE_2,
    STUFE_3,
    ZWECK_ANTWORT,
    Call,
    CheckResult,
    GroupCheckResult,
    Run,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def run(session):
    run = Run(sentra_base_url="http://sentra.invalid", repeats=1, stichprobe_seed=42)
    session.add(run)
    session.flush()
    return run


def _case(session, run, *, grenzfall=False, flagged=False, judge_flagged=False, n=0):
    case, version = case_store.create_case(
        session,
        kategorie=Kategorie.GO,
        ausgangsfrage=f"Frage {n}",
        erwartete_antwort="x",
        referenz_korrekt="y",
        grenzfall=grenzfall,
    )
    case_store.approve(session, version)
    call = Call(
        run_id=run.id,
        case_version_id=version.id,
        zweck=ZWECK_ANTWORT,
        status=OK,
        endpoint="/api/explorer/answer",
    )
    session.add(call)
    session.flush()
    if flagged:
        session.add(
            CheckResult(
                call_id=call.id, pruefung="quellenauswahl", ergebnis="falsch", auffaellig=True
            )
        )
    if judge_flagged:
        session.add(
            GroupCheckResult(
                run_id=run.id,
                case_version_id=version.id,
                pruefung="konsistenz",
                ergebnis="auffällig",
                auffaellig=True,
            )
        )
    session.flush()
    return version


# ── The rules ───────────────────────────────────────────────────────


class TestWhoReachesAHuman:
    def test_a_flagged_case_goes_to_review_as_stufe_2(self, session, run):
        version = _case(session, run, flagged=True)

        decision = triage.by_case(session, run)[version.id]

        assert decision.gefunden_ueber == STUFE_2
        assert decision.auffaellige_pruefungen == ("quellenauswahl",)

    def test_the_judge_flagging_it_counts_too(self, session, run):
        """4.1 is a verdict about the repeats, not about one call, so it comes
        from the group table — and it has to reach triage all the same."""
        version = _case(session, run, judge_flagged=True)

        decision = triage.by_case(session, run)[version.id]

        assert decision.gefunden_ueber == STUFE_2
        assert decision.auffaellige_pruefungen == ("konsistenz",)

    def test_a_clean_unsampled_case_does_not_reach_anybody(self, session, run):
        """The point of Stufe 1. Returning it would be Stufe 2 doing this job."""
        run.stichprobe_anteil = 0.0
        version = _case(session, run)

        assert triage.by_case(session, run)[version.id].needs_review is False

    def test_a_grenzfall_always_reaches_a_human(self, session, run):
        run.stichprobe_anteil = 0.0
        version = _case(session, run, grenzfall=True)

        decision = triage.by_case(session, run)[version.id]

        assert decision.gefunden_ueber == GRENZFALL_IMMER

    def test_a_flagged_grenzfall_is_still_recorded_as_a_grenzfall(self, session, run):
        """It was never eligible for filtering, so recording it as Stufe 2
        would claim Stufe 1 caught something it was never asked to catch —
        which is half of what the trend report measures."""
        version = _case(session, run, grenzfall=True, flagged=True)

        assert triage.by_case(session, run)[version.id].gefunden_ueber == GRENZFALL_IMMER


# ── Stufe 3 ─────────────────────────────────────────────────────────


class TestTheSample:
    def test_it_draws_from_the_unflagged_pool(self, session, run):
        run.stichprobe_anteil = 1.0
        clean = _case(session, run, n=1)
        flagged = _case(session, run, flagged=True, n=2)

        decisions = triage.by_case(session, run)

        assert decisions[clean.id].gefunden_ueber == STUFE_3
        assert decisions[flagged.id].gefunden_ueber == STUFE_2

    def test_grenzfaelle_are_never_in_the_pool(self, session, run):
        run.stichprobe_anteil = 1.0
        version = _case(session, run, grenzfall=True)

        assert triage.by_case(session, run)[version.id].gefunden_ueber == GRENZFALL_IMMER

    def test_the_rate_decides_how_many(self, session, run):
        run.stichprobe_anteil = 0.2
        for i in range(10):
            _case(session, run, n=i)

        sampled = [d for d in triage.triage_run(session, run) if d.gefunden_ueber == STUFE_3]

        assert len(sampled) == 2

    def test_a_rate_of_zero_samples_nothing(self, session, run):
        run.stichprobe_anteil = 0.0
        for i in range(10):
            _case(session, run, n=i)

        assert [d for d in triage.triage_run(session, run) if d.needs_review] == []

    def test_the_same_seed_draws_the_same_sample(self, session, run):
        """What makes the round auditable: the sample can be recomputed months
        later and shown to be what it claims."""
        run.stichprobe_anteil = 0.3
        for i in range(10):
            _case(session, run, n=i)

        first = {d.case_version_id for d in triage.triage_run(session, run) if d.needs_review}
        second = {d.case_version_id for d in triage.triage_run(session, run) if d.needs_review}

        assert first == second

    def test_a_different_seed_draws_a_different_sample(self, session, run):
        """Otherwise the seed is decoration and every round samples the same
        cases, which would defeat the point of sampling at all."""
        run.stichprobe_anteil = 0.3
        for i in range(20):
            _case(session, run, n=i)

        run.stichprobe_seed = 1
        first = {d.case_version_id for d in triage.triage_run(session, run) if d.needs_review}
        run.stichprobe_seed = 2
        second = {d.case_version_id for d in triage.triage_run(session, run) if d.needs_review}

        assert first != second

    def test_the_draw_does_not_depend_on_how_many_cases_there_are(self, session, run):
        """A case's position is a fact about the case and the seed. If it
        depended on the size of the round, adding a case would reshuffle the
        sample and an audit could not reconstruct it."""
        run.stichprobe_anteil = 1.0
        first_batch = [_case(session, run, n=i) for i in range(3)]
        ranks_before = [triage._sample_rank(run.stichprobe_seed, v.id) for v in first_batch]

        _case(session, run, n=99)

        assert [triage._sample_rank(run.stichprobe_seed, v.id) for v in first_batch] == ranks_before
