"""4.4 against the real judge, on the answer that caused the decision.

#109 changed 4.4 from an exact string comparison to a judged one, because
SENTRA signals "I cannot answer this from the context" in prose and the literal
refusal only appears when retrieval returns nothing — which vector search never
does. That change was verified once, by hand, against the live model. This is
the same check as a test, so it does not have to be verified by hand again.

Integration: it calls the judge. Skips with instructions when one is not
configured, rather than failing on a machine that has no hub credentials.

The three cases are the ones that decide whether the check is useful:

  the real hedge     recorded from the smoke round, and the reason for #109
  a real answer      must not read as a refusal
  answer + caveats   the dangerous one. An answer that qualifies itself is
                     still an answer, and reading it as a refusal would mark an
                     invented answer on a Grenzfall as korrekt abgelehnt
"""

import pytest

from sentra_eval import checks
from sentra_eval.judge import JudgeUnavailable, MissingJudgeConfiguration, beurteile_ablehnung

pytestmark = pytest.mark.integration

# Verbatim from run eb44a2cc, asked "Wie hoch ist die Mondtagegeldpauschale für
# Abgeordnete auf Dienstreisen zum Mars?" — a question deliberately outside the
# corpus. SENTRA retrieved ten chunks about Abgeordnetenvergütung and said this.
ECHTE_ABLEHNUNG = (
    "Die Frage kann nicht ausreichend beantwortet werden, da der Kontext keine "
    'Informationen über eine "Mondtagegeldpauschale" oder Dienstreisen zum Mars '
    "enthält. Die bereitgestellten Quellen beziehen sich auf die Vergütung von "
    "Abgeordneten im Deutschen Bundestag, die Kostenpauschale für Abgeordnete und "
    "andere damit verbundene Themen, aber nicht auf Raumfahrten oder ähnliche "
    "Aktivitäten."
)

ECHTE_ANTWORT = "Nach § 35 GOBT beträgt die Redezeit grundsätzlich 15 Minuten je Fraktion [1]."

ANTWORT_MIT_VORBEHALT = (
    "Die Redezeit beträgt 15 Minuten je Fraktion [1], wobei der Ältestenrat abweichende "
    "Regelungen treffen kann und die Angaben unvollständig sein könnten."
)


def _judged(text: str, frage: str) -> bool:
    try:
        abgelehnt, _grund = beurteile_ablehnung(text, frage=frage)
    except MissingJudgeConfiguration as exc:
        pytest.skip(f"No judge configured: {exc}")
    except JudgeUnavailable as exc:
        pytest.skip(f"The judge is not reachable: {exc}")
    return abgelehnt


class TestTheJudgeReadsRefusals:
    def test_the_answer_that_caused_the_decision_reads_as_a_refusal(self):
        """Before #109 this was flagged, and would have been in every round
        forever, because it is not the literal string."""
        assert _judged(ECHTE_ABLEHNUNG, "Wie hoch ist die Mondtagegeldpauschale zum Mars?")

    def test_a_real_answer_does_not(self):
        assert not _judged(ECHTE_ANTWORT, "Wie lange darf ein Redner sprechen?")

    def test_an_answer_with_caveats_does_not(self):
        """The dangerous direction. An answer that qualifies itself is still an
        answer; reading it as a refusal would mark an invented answer on a
        Grenzfall as korrekt abgelehnt, which is the one verdict that must not
        be wrong quietly."""
        assert not _judged(ANTWORT_MIT_VORBEHALT, "Wie lange darf ein Redner sprechen?")


class TestTheCheckAgrees:
    """The judge's verdict carried through the check, which is what a round
    actually records."""

    def test_the_grenzfall_now_passes(self):
        frage = "Wie hoch ist die Mondtagegeldpauschale zum Mars?"
        response = {"text": ECHTE_ABLEHNUNG, "sources": [{"aktenzeichen": "WD 3 - 3000 - 055/23"}]}

        outcome = checks.ablehnung(
            response, grenzfall=True, abgelehnt=_judged(ECHTE_ABLEHNUNG, frage)
        )

        assert outcome.ergebnis == checks.KORREKT_ABGELEHNT
        assert outcome.auffaellig is False
        assert outcome.belege["beurteilt_durch"] == "Prüfmodell"

    def test_and_would_have_failed_on_the_literal_comparison(self):
        """The old behaviour, kept as the fallback when no judge is reachable —
        and the reason #109 was needed."""
        response = {"text": ECHTE_ABLEHNUNG, "sources": [{"aktenzeichen": "WD 3 - 3000 - 055/23"}]}

        outcome = checks.ablehnung(response, grenzfall=True)

        assert outcome.ergebnis == checks.NICHT_ABGELEHNT
        assert outcome.auffaellig is True
