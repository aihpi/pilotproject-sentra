"""The judge: the one check that needs a model, and the ways it can lie.

4.1 and 4.2 compare answers to each other rather than to a fixed expectation,
which is why a script cannot do them. Everything else in the harness stays
deterministic.

Nothing here calls a model. The prompt construction and the parsing are what
break, and they break silently — a judge that returns something unparsable and
is read as "unauffällig" marks a case clean for a reason that has nothing to do
with the answer. So the tests are about refusing to produce a verdict, as much
as about producing one.
"""

import pytest

from sentra_eval import judge


def _reply(verdict="unauffällig", dimension=None, begruendung="Kein Unterschied."):
    import json

    return json.dumps(
        {"verdict": verdict, "dimension": dimension, "begruendung": begruendung},
        ensure_ascii=False,
    )


# ── Reading a verdict ───────────────────────────────────────────────


class TestParsing:
    def test_a_clean_verdict(self):
        got = judge.parse_verdict(_reply(), pruefung=judge.KONSISTENZ)

        assert got["verdict"] == judge.UNAUFFAELLIG
        assert got["pruefung"] == judge.KONSISTENZ

    def test_a_finding_carries_its_dimension(self):
        """Kernaussage / Zahlen / Quellen, because the trend report groups by
        it. Prose cannot be aggregated."""
        got = judge.parse_verdict(
            _reply("auffällig", "Zahlen", "15 gegen 20 Minuten."), pruefung=judge.KONSISTENZ
        )

        assert got["verdict"] == judge.AUFFAELLIG
        assert got["dimension"] == "Zahlen"
        assert got["begruendung"] == "15 gegen 20 Minuten."

    def test_json_wrapped_in_prose_is_still_read(self):
        """Models add a sentence before the JSON however firmly they are asked
        not to. That is not worth failing a round over."""
        content = f"Hier ist meine Bewertung:\n```json\n{_reply('auffällig', 'Quellen')}\n```"

        got = judge.parse_verdict(content, pruefung=judge.KONSISTENZ)

        assert got["verdict"] == judge.AUFFAELLIG

    def test_the_model_that_answered_is_recorded(self):
        """The configured name is not a guarantee of what ran."""
        got = judge.parse_verdict(_reply(), pruefung=judge.KONSISTENZ, model="qwen3-8-27b")

        assert got["judge_model"] == "qwen3-8-27b"

    def test_a_long_begruendung_is_truncated_not_dropped(self):
        got = judge.parse_verdict(_reply(begruendung="x" * 5000), pruefung=judge.KONSISTENZ)

        assert len(got["begruendung"]) == 1000


class TestRefusingToInventAVerdict:
    """The failure mode that matters. A judge whose reply cannot be read must
    not be recorded as having said "unauffällig" — that marks a case clean for
    a reason unrelated to the answer, and it is the quietest way this process
    could lie."""

    def test_no_json_at_all(self):
        with pytest.raises(judge.JudgeUnavailable, match="No JSON"):
            judge.parse_verdict("Ich bin mir nicht sicher.", pruefung=judge.KONSISTENZ)

    def test_broken_json(self):
        with pytest.raises(judge.JudgeUnavailable, match="did not parse"):
            judge.parse_verdict('{"verdict": "unauffällig",}', pruefung=judge.KONSISTENZ)

    def test_a_verdict_it_does_not_recognise(self):
        with pytest.raises(judge.JudgeUnavailable, match="Unrecognised verdict"):
            judge.parse_verdict(_reply("vielleicht"), pruefung=judge.KONSISTENZ)

    def test_a_missing_verdict(self):
        with pytest.raises(judge.JudgeUnavailable, match="Unrecognised verdict"):
            judge.parse_verdict('{"dimension": "Zahlen"}', pruefung=judge.KONSISTENZ)

    def test_an_english_verdict_is_not_quietly_accepted(self):
        """The prompt asks for German. A model answering in English has not
        followed it, and guessing the mapping would hide that."""
        with pytest.raises(judge.JudgeUnavailable):
            judge.parse_verdict(_reply("unremarkable"), pruefung=judge.KONSISTENZ)


class TestTheComparison:
    def test_fewer_than_two_answers_is_refused(self):
        with pytest.raises(judge.JudgeUnavailable, match="Fewer than two"):
            judge.compare(["nur eine"], frage="x", pruefung=judge.KONSISTENZ)


class TestThePrompt:
    """The Vorlage asks for a judge sharing neither model nor prompt structure
    with the system under test, because one that does relocates a consistency
    problem rather than detecting it."""

    def test_it_asks_about_substance_and_rules_out_wording(self):
        assert "Kernaussage" in judge.JUDGE_SYSTEM_PROMPT
        assert "Zahlen" in judge.JUDGE_SYSTEM_PROMPT
        assert "Quellen" in judge.JUDGE_SYSTEM_PROMPT
        assert "KEINE Abweichung" in judge.JUDGE_SYSTEM_PROMPT

    def test_the_token_budget_allows_for_a_reasoning_model(self):
        """gpt-oss-120b spends completion tokens reasoning before emitting any
        content — at 20 tokens it returned finish_reason "length" with an empty
        message, which would have read as a judge declining to answer."""
        assert judge.JUDGE_MAX_TOKENS >= 1000


class TestTheTokenBudget:
    """A reasoning model thinks before it answers, and a call that runs out
    mid-thought returns nothing with finish_reason "length" (#279)."""

    def _model(self, monkeypatch, replies):
        """Answers the calls in order with (content, finish_reason) and records
        each call's max_tokens."""
        calls = []

        class Completions:
            @staticmethod
            def create(**kwargs):
                calls.append(kwargs["max_tokens"])
                content, finish = replies[len(calls) - 1]
                message = type("M", (), {"content": content})()
                choice = type("C", (), {"message": message, "finish_reason": finish})()
                return type("R", (), {"choices": [choice], "model": "judge"})()

        class Client:
            def __init__(self, **kwargs):
                self.chat = type("Chat", (), {"completions": Completions})()

        monkeypatch.setattr(judge, "OpenAI", Client)
        monkeypatch.setattr(
            judge,
            "judge_config",
            lambda: type("C", (), {"base_url": "x", "api_key": "y", "model": "judge"})(),
        )
        return calls

    def test_an_answer_on_the_first_try_is_asked_once(self, monkeypatch):
        calls = self._model(monkeypatch, [('{"ok": 1}', "stop")])

        assert judge.ask_judge("s", "u", temperature=0) == ('{"ok": 1}', "judge")
        assert calls == [judge.JUDGE_MAX_TOKENS]

    def test_running_out_is_asked_again_with_twice_the_budget(self, monkeypatch):
        calls = self._model(monkeypatch, [("", "length"), ('{"ok": 1}', "stop")])

        assert judge.ask_judge("s", "u", temperature=0)[0] == '{"ok": 1}'
        assert calls == [judge.JUDGE_MAX_TOKENS, 2 * judge.JUDGE_MAX_TOKENS]

    def test_running_out_twice_is_an_error_not_a_verdict(self, monkeypatch):
        self._model(monkeypatch, [("", "length"), ("", "length")])

        with pytest.raises(judge.JudgeUnavailable, match="finish_reason='length'"):
            judge.ask_judge("s", "u", temperature=0)

    def test_an_empty_reply_for_another_reason_is_not_retried(self, monkeypatch):
        calls = self._model(monkeypatch, [("", "stop")])

        with pytest.raises(judge.JudgeUnavailable):
            judge.ask_judge("s", "u", temperature=0)
        assert len(calls) == 1
