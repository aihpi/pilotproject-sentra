"""ragas scores, mapped to verdicts.

The integration itself is exercised against the live hub; these are about the
mapping, which is where a wrong answer would be silent.

The test that matters most is the NaN one. ragas returns NaN for a metric it
could not compute, NaN fails every comparison, and `nan < schwelle` is False —
so a metric that never ran fell straight through to "ausreichend" and marked a
case clean for a reason unrelated to the answer. That was a real bug, found
against the live hub when answer correctness returned NaN because the embedding
model was wrong, and it is exactly the shape of thing a threshold check gets
wrong quietly.
"""

from sentra_eval import ragas_checks
from sentra_eval.checks import NICHT_PRUEFBAR

SCHWELLEN = {
    ragas_checks.RAGAS_TREUE: 0.7,
    ragas_checks.RAGAS_ANTWORTGUETE: 0.6,
    ragas_checks.RAGAS_KONTEXT: 0.5,
}


def _scored(monkeypatch, values):
    monkeypatch.setattr(ragas_checks, "is_available", lambda: True)
    monkeypatch.setattr(ragas_checks, "_run_ragas", lambda **kwargs: values)
    return ragas_checks.score(
        {"text": "Eine Antwort.", "hits": [{"text": "Ein Kontext."}]},
        frage="Eine Frage?",
        erwartete_antwort="Die erwartete Antwort.",
    )


# ── The mapping ─────────────────────────────────────────────────────


class TestThresholds:
    def test_a_score_above_the_threshold_passes(self, monkeypatch):
        out = _scored(monkeypatch, {ragas_checks.RAGAS_TREUE: 0.9})

        treue = next(o for o in out if o.pruefung == ragas_checks.RAGAS_TREUE)
        assert treue.ergebnis == ragas_checks.AUSREICHEND
        assert treue.auffaellig is False

    def test_a_score_below_it_is_a_finding(self, monkeypatch):
        out = _scored(monkeypatch, {ragas_checks.RAGAS_TREUE: 0.4})

        treue = next(o for o in out if o.pruefung == ragas_checks.RAGAS_TREUE)
        assert treue.ergebnis == ragas_checks.UNZUREICHEND
        assert treue.auffaellig is True

    def test_the_reviewer_reads_a_word_not_a_number(self, monkeypatch):
        """A score between zero and one is something a person has to learn to
        interpret, and two people will interpret it differently."""
        out = _scored(monkeypatch, {ragas_checks.RAGAS_TREUE: 0.62})

        treue = next(o for o in out if o.pruefung == ragas_checks.RAGAS_TREUE)
        assert treue.ergebnis in (ragas_checks.AUSREICHEND, ragas_checks.UNZUREICHEND)
        # Kept as evidence, because a verdict whose basis nobody can see is an
        # assertion — but it is not the verdict.
        assert treue.belege["wert"] == 0.62
        assert treue.belege["schwelle"] == 0.7


class TestNaN:
    """A metric that could not be computed is not a passing metric."""

    def test_nan_is_not_checkable(self, monkeypatch):
        out = _scored(monkeypatch, {ragas_checks.RAGAS_TREUE: float("nan")})

        treue = next(o for o in out if o.pruefung == ragas_checks.RAGAS_TREUE)
        assert treue.ergebnis == NICHT_PRUEFBAR

    def test_nan_is_never_reported_as_sufficient(self, monkeypatch):
        """The bug this exists for: nan < schwelle is False, so a NaN score
        fell through to "ausreichend" and marked a case clean."""
        out = _scored(monkeypatch, {ragas_checks.RAGAS_TREUE: float("nan")})

        treue = next(o for o in out if o.pruefung == ragas_checks.RAGAS_TREUE)
        assert treue.ergebnis != ragas_checks.AUSREICHEND
        assert treue.auffaellig is False  # unchecked, not failed

    def test_a_missing_metric_is_not_checkable(self, monkeypatch):
        out = _scored(monkeypatch, {})

        assert all(o.ergebnis == NICHT_PRUEFBAR for o in out)


# ── Degrading rather than failing ───────────────────────────────────


class TestWithoutTheExtra:
    def test_it_reports_not_checkable_rather_than_raising(self, monkeypatch):
        """ragas is 97 packages against this harness's twelve, so most
        deployments will not have it. A round must not fail because of that."""
        monkeypatch.setattr(ragas_checks, "is_available", lambda: False)

        out = ragas_checks.score(
            {"text": "x", "hits": [{"text": "y"}]}, frage="f", erwartete_antwort="e"
        )

        assert all(o.ergebnis == NICHT_PRUEFBAR for o in out)
        assert all("nicht installiert" in o.belege["grund"] for o in out)

    def test_a_call_without_the_debug_payload_is_not_checkable(self, monkeypatch):
        """Faithfulness and context precision are both about the retrieved
        context. Without it there is nothing to score against."""
        monkeypatch.setattr(ragas_checks, "is_available", lambda: True)

        out = ragas_checks.score({"text": "x"}, frage="f", erwartete_antwort="e")

        assert all(o.ergebnis == NICHT_PRUEFBAR for o in out)
        assert all("debug" in o.belege["grund"] for o in out)

    def test_a_ragas_failure_is_recorded_not_raised(self, monkeypatch):
        """One metric erroring must not cost the round."""
        monkeypatch.setattr(ragas_checks, "is_available", lambda: True)

        def explode(**kwargs):
            raise RuntimeError("the embedding model is wrong")

        monkeypatch.setattr(ragas_checks, "_run_ragas", explode)

        out = ragas_checks.score(
            {"text": "x", "hits": [{"text": "y"}]}, frage="f", erwartete_antwort="e"
        )

        assert all(o.ergebnis == NICHT_PRUEFBAR for o in out)
        assert all("embedding model" in o.belege["grund"] for o in out)


class TestTheContexts:
    def test_they_come_from_the_debug_hits(self):
        contexts = ragas_checks.contexts_from(
            {"hits": [{"text": "eins"}, {"text": "zwei"}, {"text": ""}]}
        )

        assert contexts == ["eins", "zwei"]

    def test_no_hits_is_no_contexts(self):
        assert ragas_checks.contexts_from({"text": "x"}) == []
