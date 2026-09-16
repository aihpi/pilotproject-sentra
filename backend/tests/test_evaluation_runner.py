"""Running a round, and being able to stop in the middle of one.

A round is roughly 180 generation calls at 20 to 29 seconds each. That number
is what shapes this: losing a round to a restart at call 45 costs an hour of
wall clock and a slice of hub quota, so the call rows are the progress record
and continuing means skipping what is already there.

SENTRA is stubbed through httpx.MockTransport. The runner is a plain HTTP
client, which is the whole point of it calling over HTTP, and that makes it
testable without a server — or a hub bill. What is *not* stubbed is the
decision-making: the plan, the resume arithmetic and the audit check all run
for real against SQLite.
"""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from sentra.evaluation import cases as case_store
from sentra.evaluation import runner
from sentra.evaluation.categories import Kategorie
from sentra.evaluation.config import get_eval_settings
from sentra.evaluation.db import Base, get_engine
from sentra.evaluation.models import FEHLER, OK, ZWECK_ANTWORT, Call, Run


def _answers(session):
    """Only the calls under test. A round also probes the document search once
    per case, for recall, and those are not answers."""
    return [c for c in session.execute(select(Call)).scalars() if c.zweck == ZWECK_ANTWORT]


ANSWER = {
    "text": "Nach § 35 GOBT gilt eine Redezeit von 15 Minuten [1].",
    "sources": [{"aktenzeichen": "WD 3 - 3000 - 029/23", "title": "Redezeit"}],
    "system_prompt": "Du bist ein Assistent ...",
}


@pytest.fixture
def db(monkeypatch, tmp_path):
    """A real database the runner opens its own sessions against."""
    monkeypatch.setenv("EVAL_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'runner.db'}")
    monkeypatch.setenv("SENTRA_BASE_URL", "http://sentra.invalid")
    get_eval_settings.cache_clear()
    get_engine.cache_clear()
    Base.metadata.create_all(get_engine())
    yield
    get_eval_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture
def session(db):
    with Session(get_engine()) as s:
        yield s


def _approved_case(session, question="Wie lange darf ein Redner sprechen?"):
    case, version = case_store.create_case(
        session,
        kategorie=Kategorie.GO,
        ausgangsfrage=question,
        erwartete_antwort="15 Minuten nach § 35 GOBT.",
        referenz_korrekt="GOBT § 35",
    )
    case_store.approve(session, version)
    session.commit()
    return case


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://sentra.invalid")


def _always(status=200, body=None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body if body is not None else ANSWER)

    return handler


# ── Planning ────────────────────────────────────────────────────────


class TestPlanning:
    def test_three_repeats_per_case(self, session):
        _approved_case(session)
        run = runner.start_run(session, repeats=3)

        # Three answers, plus one probe of the document search for recall.
        assert len(runner.plan(session, run)) == 4

    def test_a_case_with_only_a_draft_is_skipped(self, session):
        """A draft is not a yardstick. Running against one would measure an
        answer against an expectation still being written."""
        _approved_case(session)
        case_store.create_case(session, kategorie=Kategorie.GO, ausgangsfrage="Noch im Entwurf")
        session.commit()
        run = runner.start_run(session, repeats=1)

        assert len(runner.plan(session, run)) == 2  # one answer, one recall probe

    def test_the_approved_version_is_used_not_the_newest(self, session):
        """Drafting the next round's wording must not change what this round
        measures."""
        case = _approved_case(session, question="Originalfrage")
        case_store.add_version(session, case, ausgangsfrage="Neuer Entwurf")
        session.commit()
        run = runner.start_run(session, repeats=1)

        assert runner.plan(session, run)[0].frage == "Originalfrage"

    def test_a_round_with_nothing_approved_is_refused(self, session):
        """Rather than sitting at "completed, 0 calls", which looks like a
        harness that silently does nothing."""
        case_store.create_case(session, kategorie=Kategorie.GO, ausgangsfrage="Entwurf")
        session.commit()

        with pytest.raises(runner.RunnerError, match="nothing to run"):
            runner.start_run(session)


# ── Executing ───────────────────────────────────────────────────────


class TestExecuting:
    def test_every_planned_call_is_stored(self, session):
        _approved_case(session)
        run = runner.start_run(session, repeats=3)
        session.commit()

        runner.execute(run.id, _client(_always()))

        session.expire_all()
        assert len(_answers(session)) == 3

    def test_the_response_is_stored_whole(self, session):
        """Every later check is a pure function over this row, including checks
        that do not exist yet."""
        _approved_case(session)
        run = runner.start_run(session, repeats=1)
        session.commit()

        runner.execute(run.id, _client(_always()))

        session.expire_all()
        call = _answers(session)[0]
        assert call.response_body["text"] == ANSWER["text"]
        assert call.response_body["system_prompt"] == ANSWER["system_prompt"]

    def test_the_question_that_was_asked_is_stored(self, session):
        _approved_case(session, question="Sehr spezifische Frage")
        run = runner.start_run(session, repeats=1)
        session.commit()

        runner.execute(run.id, _client(_always()))

        session.expire_all()
        assert _answers(session)[0].request_body["query"] == "Sehr spezifische Frage"

    def test_a_clean_round_is_abgeschlossen(self, session):
        _approved_case(session)
        run = runner.start_run(session, repeats=2)
        session.commit()

        runner.execute(run.id, _client(_always()))

        session.expire_all()
        assert session.get(Run, run.id).status == "abgeschlossen"


# ── Failures are rows, not lost rounds ──────────────────────────────


class TestFailures:
    def test_a_503_is_stored_and_the_round_continues(self, session):
        """One blip must not cost the remaining cases."""
        _approved_case(session)
        calls: list[int] = []

        def flaky(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(503, json={"detail": "Suchdatenbank nicht erreichbar"})
            return httpx.Response(200, json=ANSWER)

        run = runner.start_run(session, repeats=3)
        session.commit()

        runner.execute(run.id, _client(flaky))

        session.expire_all()
        rows = session.execute(select(Call)).scalars().all()
        assert len(rows) == 4  # three answers plus the recall probe
        assert sum(1 for r in rows if r.status == FEHLER) == 1

    def test_a_transport_failure_is_stored_too(self, session):
        _approved_case(session)

        def unreachable(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        run = runner.start_run(session, repeats=1)
        session.commit()

        runner.execute(run.id, _client(unreachable))

        session.expire_all()
        call = _answers(session)[0]
        assert call.status == FEHLER
        assert "ConnectError" in call.fehler

    def test_a_round_with_failures_is_not_reported_clean(self, session):
        _approved_case(session)

        run = runner.start_run(session, repeats=2)
        session.commit()
        runner.execute(run.id, _client(_always(503, {"detail": "kaputt"})))

        session.expire_all()
        assert session.get(Run, run.id).status == "fehlgeschlagen"


# ── Resuming ────────────────────────────────────────────────────────


class TestResuming:
    def test_a_finished_call_is_not_repeated(self, session):
        """Repeating it would spend quota to overwrite evidence that is good."""
        _approved_case(session)
        run = runner.start_run(session, repeats=3)
        session.commit()
        runner.execute(run.id, _client(_always()))

        session.expire_all()
        run = session.get(Run, run.id)
        assert runner.outstanding(session, run) == []

    def test_failed_calls_are_retried(self, session):
        """Resuming is usually something you do because something went wrong."""
        _approved_case(session)
        run = runner.start_run(session, repeats=2)
        session.commit()
        runner.execute(run.id, _client(_always(503, {"detail": "kaputt"})))

        session.expire_all()
        run = session.get(Run, run.id)
        assert len(runner.outstanding(session, run)) == 3  # two answers, one recall probe

    def test_resuming_completes_the_round(self, session):
        _approved_case(session)
        run = runner.start_run(session, repeats=2)
        session.commit()
        runner.execute(run.id, _client(_always(503, {"detail": "kaputt"})))

        runner.execute(run.id, _client(_always()))

        session.expire_all()
        rows = session.execute(select(Call)).scalars().all()
        assert len(rows) == 3, "retrying created extra rows instead of replacing"
        assert all(r.status == OK for r in rows)
        assert session.get(Run, run.id).status == "abgeschlossen"

    def test_an_interrupted_round_keeps_what_it_did(self, session):
        """The scenario resumability exists for: the process dies partway."""
        _approved_case(session)
        made = {"n": 0}

        def dies_after_two(request: httpx.Request) -> httpx.Response:
            made["n"] += 1
            if made["n"] > 2:
                raise KeyboardInterrupt("someone stopped the container")
            return httpx.Response(200, json=ANSWER)

        run = runner.start_run(session, repeats=4)
        session.commit()
        with pytest.raises(KeyboardInterrupt):
            runner.execute(run.id, _client(dies_after_two))

        session.expire_all()
        run = session.get(Run, run.id)
        assert len(session.execute(select(Call)).scalars().all()) == 2
        assert len(runner.outstanding(session, run)) == 3  # two answers and the recall probe


# ── The audit property ──────────────────────────────────────────────


class TestAudit:
    def test_a_normal_round_is_sound(self, session):
        """Every version used was approved before the round started."""
        _approved_case(session)
        run = runner.start_run(session, repeats=1)
        session.commit()
        runner.execute(run.id, _client(_always()))

        session.expire_all()
        run = session.get(Run, run.id)
        assert runner.audit_is_sound(session, run) is True

    def test_approving_after_the_round_started_is_not(self, session):
        """The failure the case store exists to make visible: an expectation
        that could have been written to fit the answers."""
        from datetime import UTC, datetime, timedelta

        case = _approved_case(session)
        run = runner.start_run(session, repeats=1)
        session.commit()
        runner.execute(run.id, _client(_always()))

        session.expire_all()
        run = session.get(Run, run.id)
        version = case_store.latest_approved(case_store.get_case(session, case.test_id))
        version.freigegeben_at = datetime.now(UTC) + timedelta(hours=1)
        session.commit()

        assert runner.audit_is_sound(session, run) is False


# ── Checks run with the round ───────────────────────────────────────


class TestChecksDuringARun:
    """Scored as each call is stored, because what the check said at the time
    is part of the round's record."""

    def _case_with_reference(self, session, az="WD 3 - 3000 - 029/23"):
        case, version = case_store.create_case(
            session,
            kategorie=Kategorie.GO,
            ausgangsfrage="Wie lange darf ein Redner sprechen?",
            erwartete_antwort="15 Minuten.",
            referenz_korrekt="GOBT § 35",
            referenz_korrekt_az=az,
        )
        case_store.approve(session, version)
        session.commit()
        return case

    def _handler(self, az):
        def handler(request: httpx.Request) -> httpx.Response:
            if "documents" in str(request.url):
                return httpx.Response(200, json={"documents": [{"aktenzeichen": az}]})
            return httpx.Response(
                200, json={"text": "Antwort [1].", "sources": [{"aktenzeichen": az}]}
            )

        return handler

    def test_a_round_probes_the_document_search_too(self, session):
        """Once per case, not per repeat: what retrieval can find does not vary
        with the repeat."""
        self._case_with_reference(session)
        run = runner.start_run(session, repeats=3)
        session.commit()

        runner.execute(run.id, _client(self._handler("WD 3 - 3000 - 029/23")))

        session.expire_all()
        calls = session.execute(select(Call)).scalars().all()
        assert sum(1 for c in calls if c.zweck == "antwort") == 3
        assert sum(1 for c in calls if c.zweck == "recall") == 1

    def test_a_correct_citation_is_scored_unauffaellig(self, session):
        from sentra.evaluation.models import CheckResult

        self._case_with_reference(session)
        run = runner.start_run(session, repeats=1)
        session.commit()

        runner.execute(run.id, _client(self._handler("WD 3 - 3000 - 029/23")))

        session.expire_all()
        results = session.execute(select(CheckResult)).scalars().all()
        assert {r.pruefung for r in results} == {"quellenauswahl", "retrieval_recall"}
        assert all(r.auffaellig is False for r in results)

    def test_a_wrong_citation_is_flagged(self, session):
        from sentra.evaluation.models import CheckResult

        self._case_with_reference(session)
        run = runner.start_run(session, repeats=1)
        session.commit()

        runner.execute(run.id, _client(self._handler("WD 9 - 3000 - 999/25")))

        session.expire_all()
        flagged = (
            session.execute(select(CheckResult).where(CheckResult.auffaellig.is_(True)))
            .scalars()
            .all()
        )
        assert len(flagged) == 2  # cited the wrong source, and it was not retrievable

    def test_a_failed_call_is_not_scored(self, session):
        """There is nothing to check in a 503, and a verdict on one would be a
        finding about SENTRA being down rather than about its answer."""
        from sentra.evaluation.models import CheckResult

        self._case_with_reference(session)
        run = runner.start_run(session, repeats=1)
        session.commit()

        runner.execute(run.id, _client(_always(503, {"detail": "kaputt"})))

        session.expire_all()
        assert session.execute(select(CheckResult)).scalars().all() == []

    def test_a_round_can_be_rescored_without_calling_sentra(self, session):
        """The property the checks were shaped around: pure functions over
        stored rows, so a check that did not exist when a round ran can still
        score it."""
        from sentra.evaluation.models import CheckResult

        self._case_with_reference(session)
        run = runner.start_run(session, repeats=2)
        session.commit()
        runner.execute(run.id, _client(self._handler("WD 3 - 3000 - 029/23")))

        session.expire_all()
        for result in session.execute(select(CheckResult)).scalars():
            session.delete(result)
        session.commit()

        scored = runner.recheck(session, session.get(Run, run.id))
        session.commit()

        assert scored == 3
        assert len(session.execute(select(CheckResult)).scalars().all()) == 3
