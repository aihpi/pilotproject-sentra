"""Turning a complaint into a test case.

Phase 1 of the Vorlage: known problem cases from earlier feedback are taken
into a round deliberately, "da sich dort erfahrungsgemäß Schwachstellen
wiederholen".

The property worth defending is what does *not* come across. The expected
answer is the yardstick a round measures against, and prefilling it from
SENTRA's own output would let the system under test define what counts as
correct — the one thing the case store was shaped to prevent.
"""

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sentra_eval import cases as case_store
from sentra_eval import feedback
from sentra_eval.categories import Kategorie
from sentra_eval.db import Base

ENTRIES = [
    {
        "id": "fb-1",
        "timestamp": "2026-09-01T10:00:00+00:00",
        "question": "Wie lange darf ein Redner im Plenum sprechen?",
        "answer": "Die Redezeit beträgt 45 Minuten.",
        "rating": "negative",
        "comment": "Die Zahl stimmt nicht.",
    },
    {
        "id": "fb-2",
        "timestamp": "2026-09-02T10:00:00+00:00",
        "question": "Wer beruft den Ältestenrat ein?",
        "answer": "Der Präsident.",
        "rating": "positive",
        "comment": None,
    },
]


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _sentra(entries=None):
    def handler(request: httpx.Request) -> httpx.Response:
        wanted = request.url.params.get("rating")
        rows = entries if entries is not None else ENTRIES
        if wanted:
            rows = [e for e in rows if e["rating"] == wanted]
        return httpx.Response(200, json=rows)

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://sentra.invalid")


def _entry(**overrides):
    return feedback.FeedbackEntry(
        **{
            "id": "fb-1",
            "timestamp": "2026-09-01T10:00:00+00:00",
            "question": "Wie lange darf ein Redner im Plenum sprechen?",
            "answer": "Die Redezeit beträgt 45 Minuten.",
            "rating": "negative",
            "comment": "Die Zahl stimmt nicht.",
            **overrides,
        }
    )


# ── Reading it back ─────────────────────────────────────────────────


class TestFetching:
    def test_negative_feedback_by_default(self):
        """A rating somebody bothered to complain about is where the Vorlage
        expects weaknesses to repeat."""
        got = feedback.fetch(client=_sentra())

        assert [e.id for e in got] == ["fb-1"]

    def test_everything_when_asked(self):
        got = feedback.fetch(rating=None, client=_sentra())

        assert len(got) == 2

    def test_an_unreachable_sentra_is_its_own_error(self):
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        client = httpx.Client(transport=httpx.MockTransport(down), base_url="http://sentra.invalid")

        with pytest.raises(feedback.FeedbackError, match="Could not read feedback"):
            feedback.fetch(client=client)


# ── Drafting a case ─────────────────────────────────────────────────


class TestDrafting:
    def test_the_question_comes_across(self, session):
        case, _ = feedback.draft_case(session, _entry(), kategorie=Kategorie.GO)

        version = case_store.get_case(session, case.test_id).versions[-1]
        assert version.ausgangsfrage == "Wie lange darf ein Redner im Plenum sprechen?"

    def test_the_complaint_becomes_the_reason_for_inclusion(self, session):
        case, _ = feedback.draft_case(session, _entry(), kategorie=Kategorie.GO)

        version = case_store.get_case(session, case.test_id).versions[-1]
        assert "Die Zahl stimmt nicht." in version.grund_fuer_aufnahme
        assert "2026-09-01" in version.grund_fuer_aufnahme

    def test_the_answer_does_not_come_across(self, session):
        """The one that matters. A yardstick taken from the system under test
        is not a yardstick — it would let SENTRA define what counts as
        correct."""
        case, _ = feedback.draft_case(session, _entry(), kategorie=Kategorie.GO)

        version = case_store.get_case(session, case.test_id).versions[-1]
        assert version.erwartete_antwort == ""
        assert "45 Minuten" not in version.erwartete_antwort
        assert "45 Minuten" not in version.grund_fuer_aufnahme

    def test_the_answer_is_returned_to_the_reviewer(self, session):
        """So they can see what went wrong while writing the expected answer —
        on screen, not in the record."""
        _, beanstandet = feedback.draft_case(session, _entry(), kategorie=Kategorie.GO)

        assert beanstandet == "Die Redezeit beträgt 45 Minuten."

    def test_the_draft_is_not_runnable(self, session):
        """No expected answer and no reference source, so approval refuses it.
        The rule is the case store's and is inherited rather than restated."""
        case, _ = feedback.draft_case(session, _entry(), kategorie=Kategorie.GO)

        version = case_store.get_case(session, case.test_id).versions[-1]
        with pytest.raises(case_store.IncompleteCase):
            case_store.approve(session, version)

    def test_an_entry_with_no_question_is_refused(self, session):
        with pytest.raises(feedback.FeedbackError, match="no question"):
            feedback.draft_case(session, _entry(question="  "), kategorie=Kategorie.GO)


class TestImportingTwice:
    def test_the_same_complaint_cannot_become_two_cases(self, session):
        """It would weight one problem more heavily than the rest of the
        round."""
        feedback.draft_case(session, _entry(), kategorie=Kategorie.GO)

        with pytest.raises(feedback.AlreadyImported, match="TF-GO-001"):
            feedback.draft_case(session, _entry(), kategorie=Kategorie.GO)

    def test_a_different_complaint_still_can(self, session):
        feedback.draft_case(session, _entry(), kategorie=Kategorie.GO)

        case, _ = feedback.draft_case(
            session, _entry(id="fb-9", question="Etwas anderes?"), kategorie=Kategorie.GO
        )

        assert case.test_id == "TF-GO-002"

    def test_the_origin_is_recorded_on_the_case(self, session):
        case, _ = feedback.draft_case(session, _entry(), kategorie=Kategorie.GO)

        version = case_store.get_case(session, case.test_id).versions[-1]
        assert version.feedback_id == "fb-1"
