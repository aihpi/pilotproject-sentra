"""4.2: paraphrases proposed by a model, approved by a person.

The Vorlage is explicit that only what "inhaltlich eindeutig dasselbe meint"
may be approved, because a variant that quietly asks a different question does
not measure robustness — it measures whether SENTRA answers two different
questions the same way, which nobody wants to know.

So most of these are about the approval gate and about what happens to a
variant once a round may have measured against it. The model call itself is
stubbed: what breaks is the parsing and the freezing, not the request.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sentra_eval import cases as case_store
from sentra_eval import variants
from sentra_eval.categories import Kategorie
from sentra_eval.db import Base
from sentra_eval.judge import JudgeUnavailable
from sentra_eval.models import FREIGEGEBEN, VORGESCHLAGEN, Variant

REPLY = (
    '{"umgangssprachlich": "Wie lange darf einer im Plenum reden?",'
    ' "fachsprachlich": "Welche Redezeitregelung gilt gemäß GOBT im Plenum?",'
    ' "verkuerzt": "Redezeit Plenum Regelung"}'
)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def version(session):
    _, version = case_store.create_case(
        session,
        kategorie=Kategorie.GO,
        ausgangsfrage="Wie lange darf ein Redner im Plenum sprechen?",
        erwartete_antwort="15 Minuten.",
        referenz_korrekt="GOBT § 35",
    )
    case_store.approve(session, version)
    session.flush()
    return version


def _proposed(session, version):
    for stil, wortlaut in (
        ("umgangssprachlich", "Wie lange darf einer reden?"),
        ("fachsprachlich", "Welche Redezeitregelung gilt?"),
        ("verkuerzt", "Redezeit Plenum"),
    ):
        session.add(
            Variant(
                case_version_id=version.id,
                stil=stil,
                wortlaut=wortlaut,
                erstellt_durch=variants.ERSTELLT_DURCH_LLM,
            )
        )
    session.flush()
    return variants.for_version(session, version.id)


# ── Reading what the model proposed ─────────────────────────────────


class TestParsing:
    def test_three_styles_come_back(self):
        got = variants.parse_variants(REPLY)

        assert set(got) == {"umgangssprachlich", "fachsprachlich", "verkuerzt"}

    def test_json_wrapped_in_prose_is_still_read(self):
        got = variants.parse_variants(f"Gerne:\n```json\n{REPLY}\n```")

        assert got["verkuerzt"] == "Redezeit Plenum Regelung"

    def test_a_missing_style_is_refused(self):
        """Not filled in with the original question: that would silently turn a
        robustness check into a fourth repeat, and 4.2 would report stability
        it never tested."""
        with pytest.raises(JudgeUnavailable, match="verkuerzt"):
            variants.parse_variants(
                '{"umgangssprachlich": "a", "fachsprachlich": "b", "verkuerzt": ""}'
            )

    def test_no_json_is_refused(self):
        with pytest.raises(JudgeUnavailable, match="No JSON"):
            variants.parse_variants("Ich habe leider keine Ideen.")


# ── The approval gate ───────────────────────────────────────────────


class TestApproval:
    def test_a_proposal_is_not_yet_runnable(self, session, version):
        _proposed(session, version)

        assert variants.approved_for(session, version.id) == []

    def test_approving_makes_it_runnable(self, session, version):
        proposals = _proposed(session, version)

        variants.approve(session, proposals[0], freigegeben_durch="WD")

        assert len(variants.approved_for(session, version.id)) == 1

    def test_an_approval_needs_a_name(self, session, version):
        """ "Varianten freigegeben durch" on the Phase-4 sheet. An approval
        nobody owns is one nobody can be asked about."""
        proposals = _proposed(session, version)

        with pytest.raises(variants.VariantError, match="needs a name"):
            variants.approve(session, proposals[0], freigegeben_durch="  ")

    def test_approving_records_who_and_when(self, session, version):
        proposals = _proposed(session, version)

        variants.approve(session, proposals[0], freigegeben_durch="Hotline / M. Schmidt")

        assert proposals[0].status == FREIGEGEBEN
        assert proposals[0].freigegeben_durch == "Hotline / M. Schmidt"
        assert proposals[0].freigegeben_at is not None


class TestEditingBeforeApproval:
    def test_a_proposal_can_be_corrected(self, session, version):
        """A reviewer who can only accept or reject rejects three good variants
        over one clumsy word."""
        proposals = _proposed(session, version)

        variants.edit(session, proposals[0], "Wie lange darf jemand im Plenum reden?")

        assert proposals[0].wortlaut == "Wie lange darf jemand im Plenum reden?"
        assert proposals[0].status == VORGESCHLAGEN

    def test_an_approved_variant_is_frozen(self, session, version):
        """The same rule the expected answer has: a round measured robustness
        against these words, and changing them makes the result
        unexplainable."""
        proposals = _proposed(session, version)
        variants.approve(session, proposals[0], freigegeben_durch="WD")

        with pytest.raises(variants.ApprovedVariantIsFrozen):
            variants.edit(session, proposals[0], "etwas anderes")


class TestRegenerating:
    def test_it_replaces_proposals(self, session, version, monkeypatch):
        proposals = _proposed(session, version)
        original = proposals[0].wortlaut
        _stub_model(monkeypatch)

        variants.propose(session, version)

        assert variants.for_version(session, version.id)[0].wortlaut != original

    def test_it_leaves_approved_variants_alone(self, session, version, monkeypatch):
        """Regenerating is a normal thing to want when the first attempt was
        poor. Losing an approval to it would not be — a round may already have
        measured against that wording."""
        proposals = _proposed(session, version)
        approved = next(p for p in proposals if p.stil == "fachsprachlich")
        variants.approve(session, approved, freigegeben_durch="WD")
        kept = approved.wortlaut
        _stub_model(monkeypatch)

        variants.propose(session, version)

        still = next(
            v for v in variants.for_version(session, version.id) if v.stil == "fachsprachlich"
        )
        assert still.wortlaut == kept
        assert still.is_approved


def _stub_model(monkeypatch):
    """Answer as the judge model would, without calling it."""

    class Message:
        content = REPLY

    class Choice:
        message = Message()
        finish_reason = "stop"

    class Completion:
        choices = [Choice()]

    class Chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                return Completion()

    class Client:
        def __init__(self, **kwargs):
            self.chat = Chat()

    monkeypatch.setattr(variants, "OpenAI", Client)
    monkeypatch.setattr(
        variants,
        "judge_config",
        lambda: type("C", (), {"base_url": "x", "api_key": "y", "model": "z"})(),
    )
