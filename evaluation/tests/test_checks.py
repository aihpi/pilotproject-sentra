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

from sentra_eval import checks
from sentra_eval.models import CaseVersion

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


# ── Marker alignment ────────────────────────────────────────────────


def _answer_text(text: str, *aktenzeichen: str) -> dict:
    return {
        "text": text,
        "sources": [{"aktenzeichen": az, "title": "x"} for az in aktenzeichen],
    }


class TestMarkerAusrichtung:
    """Both prompts say [n] is the nth source in order of first appearance.
    Nothing enforces it: the model counts for itself."""

    def test_markers_matching_sources_are_unauffaellig(self):
        outcome = checks.marker_ausrichtung(_answer_text("Erstens [1], zweitens [2].", "A", "B"))

        assert outcome.ergebnis == checks.AUSGERICHTET
        assert outcome.auffaellig is False

    def test_a_marker_with_no_source_is_a_finding(self):
        """The visible half: a reviewer following [3] finds nothing there."""
        outcome = checks.marker_ausrichtung(_answer_text("Laut [3] gilt ...", "A", "B"))

        assert outcome.ergebnis == checks.NICHT_AUSGERICHTET
        assert outcome.belege["marker_ohne_quelle"] == [3]

    def test_a_source_nobody_cited_is_recorded_but_not_flagged(self):
        """Evidence, not a finding, and that is a decision from the first real
        round: both answers in it hedged, cited nothing, and had every source
        uncited — an auffällig on ordinary behaviour, on top of the ablehnung
        finding the same hedge already caused. One fact, two findings, and the
        real error class buried under them."""
        outcome = checks.marker_ausrichtung(_answer_text("Nur [1].", "A", "B", "C"))

        assert outcome.ergebnis == checks.AUSGERICHTET
        assert outcome.auffaellig is False
        # Still counted, so the trend report can ask how often answers ignore
        # their context.
        assert outcome.belege["quellen_ohne_marker"] == [2, 3]

    def test_a_hedge_that_cites_nothing_is_not_a_marker_finding(self):
        """The shape that actually came back from the live corpus: an answer
        explaining that the context does not cover the question, with sources
        attached and no markers at all."""
        outcome = checks.marker_ausrichtung(
            _answer_text("Die Frage kann auf Basis der Auszüge nicht beantwortet werden.", "A", "B")
        )

        assert outcome.auffaellig is False
        assert outcome.belege["quellen_ohne_marker"] == [1, 2]

    def test_markdown_bold_around_a_marker_still_counts(self):
        """The prompts ask for **[1]**, which is what the model emits."""
        outcome = checks.marker_ausrichtung(_answer_text("Laut **[1]** gilt ...", "A"))

        assert outcome.ergebnis == checks.AUSGERICHTET

    def test_a_marker_used_twice_is_not_a_problem(self):
        outcome = checks.marker_ausrichtung(_answer_text("[1] und später wieder [1].", "A"))

        assert outcome.ergebnis == checks.AUSGERICHTET

    def test_an_answer_with_no_markers_and_no_sources_is_fine(self):
        outcome = checks.marker_ausrichtung(_answer_text("Keine Quellenangabe nötig."))

        assert outcome.ergebnis == checks.AUSGERICHTET

    def test_the_evidence_names_both_directions(self):
        """A dangling marker still is a finding — it is the model inventing a
        citation, and a reviewer following [4] finds nothing."""
        outcome = checks.marker_ausrichtung(_answer_text("[1] und [4].", "A", "B"))

        assert outcome.ergebnis == checks.NICHT_AUSGERICHTET
        assert outcome.auffaellig is True
        assert outcome.belege["marker_ohne_quelle"] == [4]
        assert outcome.belege["quellen_ohne_marker"] == [2]


# ── 4.4, the refusal ────────────────────────────────────────────────


REFUSAL = {"text": checks.REFUSAL_TEXT, "sources": []}


class TestAblehnung:
    def test_a_grenzfall_that_is_refused_is_correct(self):
        outcome = checks.ablehnung(REFUSAL, grenzfall=True)

        assert outcome.ergebnis == checks.KORREKT_ABGELEHNT
        assert outcome.auffaellig is False

    def test_a_grenzfall_that_gets_an_answer_is_a_finding(self):
        """Where the real risk sits: a system that invents rather than saying
        it has nothing is worse than one that finds nothing."""
        outcome = checks.ablehnung(_answer_text("Dazu gilt Folgendes [1].", "A"), grenzfall=True)

        assert outcome.ergebnis == checks.NICHT_ABGELEHNT
        assert outcome.auffaellig is True

    def test_an_ordinary_question_that_is_refused_is_also_a_finding(self):
        """Retrieval returned nothing for something the corpus should cover."""
        outcome = checks.ablehnung(REFUSAL, grenzfall=False)

        assert outcome.ergebnis == checks.ABLEHNUNG_UNERWARTET
        assert outcome.auffaellig is True

    def test_an_ordinary_question_that_is_answered_says_so(self):
        """Not "korrekt abgelehnt", which is what it used to say about answers
        that were never refused — a verdict contradicting its own evidence,
        which a reviewer stops on every time."""
        outcome = checks.ablehnung(_answer_text("Antwort [1].", "A"), grenzfall=False)

        assert outcome.ergebnis == checks.KEINE_ABLEHNUNG_ERWARTET
        assert outcome.auffaellig is False

    def test_the_refusal_text_with_sources_does_not_count(self):
        """The refusal means nothing was retrieved. The same sentence with
        sources attached is something else, and not a refusal."""
        outcome = checks.ablehnung(
            {"text": checks.REFUSAL_TEXT, "sources": [{"aktenzeichen": "A"}]}, grenzfall=True
        )

        assert outcome.ergebnis == checks.NICHT_ABGELEHNT

    def test_nearly_the_refusal_text_does_not_count(self):
        outcome = checks.ablehnung(
            {"text": "Es wurden leider keine relevanten Dokumente gefunden.", "sources": []},
            grenzfall=True,
        )

        assert outcome.ergebnis == checks.NICHT_ABGELEHNT

    def test_prose_hedging_counts_when_the_judge_says_so(self):
        """#109: 4.4 accepts prose. The exact string only appears when
        retrieval returns nothing, and vector search always returns the top-k
        however irrelevant — so holding out for it meant flagging every
        Grenzfall in every round."""
        hedge = _answer_text(
            "Die Frage kann auf Basis der Auszüge nicht beantwortet werden.", "A", "B"
        )

        outcome = checks.ablehnung(hedge, grenzfall=True, abgelehnt=True)

        assert outcome.ergebnis == checks.KORREKT_ABGELEHNT
        assert outcome.auffaellig is False

    def test_the_same_hedge_without_the_judge_is_still_a_finding(self):
        """The fallback when the judge cannot be reached: conservative, and it
        sends a human to look rather than passing silently."""
        hedge = _answer_text(
            "Die Frage kann auf Basis der Auszüge nicht beantwortet werden.", "A", "B"
        )

        outcome = checks.ablehnung(hedge, grenzfall=True)

        assert outcome.ergebnis == checks.NICHT_ABGELEHNT

    def test_an_ordinary_question_that_hedges_is_a_finding(self):
        """The direction that was previously invisible: retrieval found nothing
        useful for something the corpus should cover, and SENTRA said so in
        prose rather than emitting the exact string."""
        hedge = _answer_text("Dazu liegen keine passenden Auszüge vor.", "A")

        outcome = checks.ablehnung(hedge, grenzfall=False, abgelehnt=True)

        assert outcome.ergebnis == checks.ABLEHNUNG_UNERWARTET
        assert outcome.auffaellig is True

    def test_the_evidence_says_who_decided(self):
        """A reviewer should be able to tell a literal match from a model's
        judgement, because the second can be wrong."""
        hedge = _answer_text("Kann ich nicht beantworten.", "A")

        judged = checks.ablehnung(hedge, grenzfall=True, abgelehnt=True)
        literal = checks.ablehnung(REFUSAL, grenzfall=True)

        assert judged.belege["beurteilt_durch"] == "Prüfmodell"
        assert literal.belege["beurteilt_durch"] == "Wortlaut"

    def test_the_literal_refusal_needs_no_judge(self):
        """The cheap path. The exact string with no sources is unambiguous, so
        a round spends no model call recognising it."""
        assert checks.ist_wortliche_ablehnung(REFUSAL) is True
        assert checks.ist_wortliche_ablehnung(_answer_text("Eine Antwort.", "A")) is False

    def test_the_expected_string_is_pinned(self):
        """The harness is a separate distribution and cannot import SENTRA's
        copy of this sentence. So it asserts it: rewording the refusal over
        there has to fail here loudly, rather than silently passing every
        Grenzfall from then on."""
        assert checks.REFUSAL_TEXT == "Es wurden keine relevanten Dokumente gefunden."


# ── Truncation is not inconsistency ─────────────────────────────────


class TestAbschneidung:
    def test_a_finished_answer_is_vollstaendig(self):
        outcome = checks.abschneidung({"text": "Fertig.", "finish_reason": "stop"})

        assert outcome.ergebnis == checks.VOLLSTAENDIG
        assert outcome.auffaellig is False

    def test_hitting_the_ceiling_is_a_finding(self):
        """Fachfrage generates at 2048 tokens and Überblick at 3072. Without
        finish_reason this reads as an inconsistent answer and gets filed
        against the model instead of against a configured limit."""
        outcome = checks.abschneidung({"text": "Angefangen ...", "finish_reason": "length"})

        assert outcome.ergebnis == checks.ABGESCHNITTEN
        assert outcome.auffaellig is True

    def test_without_the_debug_flag_it_is_not_checkable(self):
        outcome = checks.abschneidung({"text": "Etwas."})

        assert outcome.ergebnis == checks.NICHT_PRUEFBAR
        assert outcome.auffaellig is False


# ── The cheap half of 4.1 ───────────────────────────────────────────


class TestWiederholbarkeit:
    def test_identical_repeats_answer_4_1_without_a_judge(self):
        outcome = checks.wiederholbarkeit(["Die Antwort.", "Die Antwort.", "Die Antwort."])

        assert outcome.ergebnis == checks.IDENTISCH
        assert outcome.auffaellig is False

    def test_whitespace_alone_does_not_make_them_different(self):
        outcome = checks.wiederholbarkeit(["Die Antwort.", "Die Antwort.\n"])

        assert outcome.ergebnis == checks.IDENTISCH

    def test_differing_repeats_are_not_a_finding_on_their_own(self):
        """Differing wording is exactly what the judge exists to read. Flagging
        it here would send every case to a human for being phrased differently
        twice, which is the opposite of what Stufe 1 is for."""
        outcome = checks.wiederholbarkeit(["Die Antwort.", "Eine andere Antwort."])

        assert outcome.ergebnis == checks.ABWEICHEND
        assert outcome.auffaellig is False

    def test_the_evidence_says_how_many_differed(self):
        outcome = checks.wiederholbarkeit(["A", "B", "B"])

        assert outcome.belege["anzahl_laeufe"] == 3
        assert outcome.belege["verschiedene_antworten"] == 2

    def test_one_repeat_cannot_be_compared(self):
        outcome = checks.wiederholbarkeit(["Nur eine."])

        assert outcome.ergebnis == checks.NICHT_PRUEFBAR


# ── 4.3a: does the cited page hold the passage? ─────────────────────


class TestSeitenangabe:
    """The last of the four techniques to get an automated check.

    4.3a asks whether a citation points at the passage supporting the claim.
    Until the model was shown a page it could not name one and there was
    nothing to check, which is why marker alignment carried 4.3a as far as the
    data allowed and no further.

    Reported in the Vorlage's own words, because a reviewer picks from those
    for 4.3a and the comparison between the two answers is what the
    disagreement rate measures. A check with its own vocabulary agrees with
    nothing and therefore measures nothing.
    """

    def _hit(self, page_from: int, page_to: int | None = None) -> dict:
        return {"page_from": page_from, "page_to": page_to or page_from}

    def test_a_page_the_answer_drew_on_is_correct(self):
        outcome = checks.seitenangabe(
            {"text": "Nach § 35 GOBT gilt eine Redezeit von 15 Minuten (Seite 4)."},
            [self._hit(4)],
        )

        assert outcome.ergebnis == "existiert & stimmt überein"
        assert outcome.auffaellig is False

    def test_a_page_it_did_not_is_a_finding(self):
        outcome = checks.seitenangabe(
            {"text": "Die Redezeit ist auf Seite 9 geregelt."}, [self._hit(4)]
        )

        assert outcome.ergebnis == "weicht ab"
        assert outcome.auffaellig is True
        assert outcome.belege["abweichende_seiten"] == [9]

    def test_a_page_inside_a_chunk_that_spans_several(self):
        """A chunk crossing a page break covers every page between its ends."""
        outcome = checks.seitenangabe({"text": "Siehe Seite 5."}, [self._hit(4, 6)])

        assert outcome.ergebnis == "existiert & stimmt überein"

    def test_the_union_across_chunks_counts(self):
        """The answer saw all of them, so a page belonging to any is one it
        legitimately drew on. Attributing a sentence to one chunk would need to
        know which claim came from where — that is 4.3c's question."""
        outcome = checks.seitenangabe(
            {"text": "Seite 4 und Seite 11."}, [self._hit(4), self._hit(11)]
        )

        assert outcome.ergebnis == "existiert & stimmt überein"

    def test_short_form_is_read(self):
        outcome = checks.seitenangabe({"text": "Vgl. S. 4."}, [self._hit(4)])

        assert outcome.ergebnis == "existiert & stimmt überein"


class TestSeitenangabeStaysQuiet:
    """The failure mode that would matter most. A false "weicht ab" on a
    correct citation teaches reviewers to ignore the check, and a check nobody
    believes is worse than no check at all."""

    def _hit(self, page: int) -> dict:
        return {"page_from": page, "page_to": page}

    def test_an_answer_naming_no_page_is_not_prueftbar(self):
        """It cannot be wrong about a page it did not name. Calling that
        correct would make the check read as healthy on exactly the answers
        4.3a cannot vouch for."""
        outcome = checks.seitenangabe(
            {"text": "Nach § 35 GOBT gilt eine Redezeit von 15 Minuten [1]."}, [self._hit(4)]
        )

        assert outcome.ergebnis == checks.NICHT_PRUEFBAR
        assert outcome.auffaellig is False

    def test_chunks_without_a_page_are_not_prueftbar_either(self):
        """Every chunk written before the provenance work, which is all of them
        until the corpus is re-ingested. Flagging the whole corpus would be the
        check's first act."""
        outcome = checks.seitenangabe({"text": "Siehe Seite 4."}, [{"page_from": 0, "page_to": 0}])

        assert outcome.ergebnis == checks.NICHT_PRUEFBAR
        assert "Neuindexierung" in outcome.belege["grund"]

    def test_and_so_is_an_answer_with_no_sources_at_all(self):
        outcome = checks.seitenangabe({"text": "Siehe Seite 4."}, [])

        assert outcome.ergebnis == checks.NICHT_PRUEFBAR

    def test_a_paragraph_number_is_not_mistaken_for_a_page(self):
        """ "Absatz 3" is not a page, and reading it as one would flag a correct
        citation on every answer that mentions a paragraph."""
        outcome = checks.seitenangabe(
            {"text": "Nach Absatz 3 der Vorschrift, Seite 4."}, [self._hit(4)]
        )

        assert outcome.ergebnis == "existiert & stimmt überein"

    def test_a_paragraph_symbol_is_not_a_page(self):
        """§ 35 is a provision. German legal prose is full of them, and every
        one would be a false finding."""
        outcome = checks.seitenangabe({"text": "Nach § 35 GOBT."}, [self._hit(4)])

        assert outcome.ergebnis == checks.NICHT_PRUEFBAR

    def test_an_aktenzeichen_is_not_a_page(self):
        """ "WD 3 - 3000 - 029/23" carries numbers that are not pages."""
        outcome = checks.seitenangabe({"text": "Vgl. WD 3 - 3000 - 029/23."}, [self._hit(4)])

        assert outcome.ergebnis == checks.NICHT_PRUEFBAR

    def test_abs_is_not_read_as_a_page(self):
        """The one that was actually broken, and the worst one to get wrong.

        `(?:Seiten?|S\\.)` under IGNORECASE matches the "s." ending "Abs.", so
        "Abs. 3" came out as page 3 and the answer was flagged. German legal
        prose abbreviates Absatz on nearly every page, so this was not an edge
        case — it was most answers.
        """
        outcome = checks.seitenangabe(
            {"text": "Nach Abs. 3 der Vorschrift, Seite 4."}, [self._hit(4)]
        )

        assert outcome.belege["genannte_seiten"] == [4]
        assert outcome.ergebnis == "existiert & stimmt überein"

    def test_the_projects_own_citation_format_passes(self):
        """ "S. 4, Abs. 3" is the shape #134 put into the prompt and the shape
        `format_location()` emits. A check that flags the format the system
        under test was told to use measures the check, not the system."""
        outcome = checks.seitenangabe({"text": "Siehe S. 4, Abs. 3."}, [self._hit(4)])

        assert outcome.belege["genannte_seiten"] == [4]
        assert outcome.ergebnis == "existiert & stimmt überein"

    def test_an_absatz_alone_is_not_prueftbar(self):
        """No page named at all, so there is nothing to compare — not a pass
        and not a finding."""
        outcome = checks.seitenangabe({"text": "Gemäß Abs. 9."}, [self._hit(4)])

        assert outcome.belege["genannte_seiten"] == []
        assert outcome.ergebnis == checks.NICHT_PRUEFBAR

    def test_lowercase_s_is_left_alone(self):
        """In German prose "s. dazu" abbreviates *siehe*, not Seite. Reading it
        as a page would invent a citation the answer never made."""
        outcome = checks.seitenangabe({"text": "s. dazu 9 weitere Fälle."}, [self._hit(4)])

        assert outcome.ergebnis == checks.NICHT_PRUEFBAR

    def test_the_evidence_says_what_was_compared(self):
        """A reviewer disagreeing with this needs to see what it looked at —
        the disagreement is the measurement, so it has to be arguable."""
        outcome = checks.seitenangabe({"text": "Seite 9."}, [self._hit(4)])

        assert outcome.belege["genannte_seiten"] == [9]
        assert outcome.belege["seiten_der_quellen"] == [4]
