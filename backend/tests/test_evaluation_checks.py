"""4.3b and retrieval recall, over stored responses.

These are the cheapest real checks in the harness and the ones most able to do
harm, because a false finding costs the most expensive thing in this process:
a reviewer reading a document that was cited correctly.

So the cases that matter most here are the ones where the check must *not*
fire — a differently spaced Aktenzeichen, a case with no Aktenzeichen recorded
at all — and the one where it must fire even though the answer looks right:
the outdated source cited alongside the correct one.

Pure functions over dictionaries. No database, no HTTP, which is the property
that lets a finished round be re-checked later by a check that did not exist
when it ran.
"""

import pytest

from sentra.evaluation import checks
from sentra.evaluation.models import CaseVersion

KORREKT = "WD 3 - 3000 - 029/23"
VERALTET = "WD 3 - 3000 - 011/19"


def _version(korrekt: str = KORREKT, falsch: str = VERALTET) -> CaseVersion:
    return CaseVersion(
        ausgangsfrage="Wie lange darf ein Redner sprechen?",
        erwartete_antwort="15 Minuten.",
        referenz_korrekt="GOBT § 35",
        referenz_falsch="GOBT § 35 a. F.",
        referenz_korrekt_az=korrekt,
        referenz_falsch_az=falsch,
    )


def _answer(*aktenzeichen: str) -> dict:
    return {
        "text": "Eine Antwort [1].",
        "sources": [{"aktenzeichen": az, "title": "Ein Dokument"} for az in aktenzeichen],
    }


def _documents(*aktenzeichen: str) -> dict:
    return {"documents": [{"aktenzeichen": az, "title": "x"} for az in aktenzeichen]}


# ── Normalisation, because a false finding is expensive ─────────────


class TestAktenzeichenMatching:
    @pytest.mark.parametrize(
        "written",
        [
            "WD 3 - 3000 - 029/23",
            "WD 3-3000-029/23",
            "WD 3  -  3000  -  029/23",
            "wd 3 - 3000 - 029/23",
        ],
    )
    def test_the_same_document_written_differently_still_matches(self, written):
        """Spacing varies with whoever typed it. A check that called these
        different would report a wrong source on a right answer, and send a
        reviewer to read a document that was cited correctly."""
        outcome = checks.quellenauswahl(_answer(written), _version())

        assert outcome.ergebnis == checks.KORREKTE_QUELLE

    def test_a_genuinely_different_document_does_not_match(self):
        outcome = checks.quellenauswahl(_answer("WD 3 - 3000 - 030/23"), _version())

        assert outcome.ergebnis == checks.FALSCHE_QUELLE


# ── 4.3b ────────────────────────────────────────────────────────────


class TestQuellenauswahl:
    def test_citing_the_correct_source_is_unauffaellig(self):
        outcome = checks.quellenauswahl(_answer(KORREKT), _version())

        assert outcome.ergebnis == checks.KORREKTE_QUELLE
        assert outcome.auffaellig is False

    def test_citing_the_outdated_source_is_a_finding(self):
        """What the two reference fields exist to catch."""
        outcome = checks.quellenauswahl(_answer(VERALTET), _version())

        assert outcome.ergebnis == checks.FALSCHE_QUELLE
        assert outcome.auffaellig is True

    def test_citing_both_is_still_a_finding(self):
        """An answer that drew on both still drew on the outdated one, and a
        reviewer needs to see it. Letting the correct source excuse it is how a
        wrong Paragraphennummer reaches a Hotline answer."""
        outcome = checks.quellenauswahl(_answer(KORREKT, VERALTET), _version())

        assert outcome.ergebnis == checks.FALSCHE_QUELLE
        assert outcome.auffaellig is True

    def test_citing_neither_is_a_finding(self):
        outcome = checks.quellenauswahl(_answer("WD 9 - 3000 - 001/25"), _version())

        assert outcome.ergebnis == checks.FALSCHE_QUELLE

    def test_citing_nothing_at_all_is_a_finding(self):
        outcome = checks.quellenauswahl({"text": "...", "sources": []}, _version())

        assert outcome.ergebnis == checks.FALSCHE_QUELLE

    def test_a_case_without_an_aktenzeichen_is_not_checkable(self):
        """A real state — a legal question SENTRA holds no document for — not a
        failure. Reporting it as failed would fill the first round with
        findings about the case file rather than about SENTRA."""
        outcome = checks.quellenauswahl(_answer(KORREKT), _version(korrekt=""))

        assert outcome.ergebnis == checks.NICHT_PRUEFBAR
        assert outcome.auffaellig is False

    def test_a_case_without_a_wrong_reference_still_checks_the_right_one(self):
        """referenz_falsch is optional. Its absence weakens the check but does
        not disable it."""
        outcome = checks.quellenauswahl(_answer(KORREKT), _version(falsch=""))

        assert outcome.ergebnis == checks.KORREKTE_QUELLE

    def test_the_evidence_shows_what_was_cited(self):
        """A verdict a reviewer cannot check is an assertion."""
        outcome = checks.quellenauswahl(_answer(VERALTET), _version())

        assert outcome.belege["zitierte_quellen"] == [VERALTET]
        assert outcome.belege["referenz_falsch_zitiert"] is True


# ── Retrieval recall ────────────────────────────────────────────────


class TestRetrievalRecall:
    def test_the_rank_is_reported(self):
        outcome = checks.retrieval_recall(
            _documents("WD 1 - 3000 - 001/24", KORREKT, "WD 2 - 3000 - 002/24"), _version()
        )

        assert outcome.ergebnis == checks.GEFUNDEN
        assert outcome.belege["rang"] == 2

    def test_rank_one_is_still_gefunden(self):
        outcome = checks.retrieval_recall(_documents(KORREKT), _version())

        assert outcome.belege["rang"] == 1

    def test_absent_from_the_document_search_is_a_finding(self):
        """This is the distinction the probe exists for. Missing here is a
        retrieval problem; missing from the answer while present here is a
        ranking problem, and they need different people to look at them."""
        outcome = checks.retrieval_recall(_documents("WD 9 - 3000 - 001/25"), _version())

        assert outcome.ergebnis == checks.NICHT_GEFUNDEN
        assert outcome.auffaellig is True
        assert outcome.belege["rang"] is None

    def test_an_empty_result_is_a_finding(self):
        outcome = checks.retrieval_recall({"documents": []}, _version())

        assert outcome.ergebnis == checks.NICHT_GEFUNDEN

    def test_a_case_without_an_aktenzeichen_is_not_checkable(self):
        outcome = checks.retrieval_recall(_documents(KORREKT), _version(korrekt=""))

        assert outcome.ergebnis == checks.NICHT_PRUEFBAR

    def test_spacing_does_not_matter_here_either(self):
        outcome = checks.retrieval_recall(_documents("WD 3-3000-029/23"), _version())

        assert outcome.ergebnis == checks.GEFUNDEN


# ── The combination the probe exists to separate ────────────────────


class TestTheDistinctionThatMatters:
    def test_missing_from_the_answer_but_found_by_search_is_a_ranking_problem(self):
        """`/answer` searches at raw top_k (10); `/documents` searches top_k * 3
        and aggregates. A source missing from an answer is usually a chunk at
        rank 11, not a retrieval failure."""
        version = _version()
        answer = checks.quellenauswahl(_answer("WD 9 - 3000 - 001/25"), version)
        recall = checks.retrieval_recall(_documents("WD 9 - 3000 - 001/25", KORREKT), version)

        assert answer.auffaellig is True
        assert recall.ergebnis == checks.GEFUNDEN
        assert recall.belege["rang"] == 2

    def test_missing_from_both_is_a_retrieval_problem(self):
        version = _version()
        answer = checks.quellenauswahl(_answer("WD 9 - 3000 - 001/25"), version)
        recall = checks.retrieval_recall(_documents("WD 9 - 3000 - 001/25"), version)

        assert answer.auffaellig is True
        assert recall.ergebnis == checks.NICHT_GEFUNDEN
