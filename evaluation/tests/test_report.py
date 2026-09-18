"""The Phase-4 sheets, and the number the whole process is calibrated by.

Section 6 of the Vorlage calls the disagreement between the automatic verdict
and the human one "die wichtigste Kennzahl, um zu beurteilen, ob sich die
Prüfschwelle in Stufe 1 zu großzügig oder zu streng eingestellt ist".

Most of these tests are about that one number, and specifically about the
distinction that makes it useful: a check that fired and was wrong says the
threshold is too strict, a check that stayed quiet while a human found
something says it is too lenient, and those are opposite instructions. A single
count of findings conflates them, which is the easy thing to build by accident.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sentra_eval import cases as case_store
from sentra_eval import report
from sentra_eval.categories import Kategorie
from sentra_eval.db import Base
from sentra_eval.models import (
    OK,
    QUELLE_FALSCH,
    QUELLE_KORREKT,
    ZWECK_ANTWORT,
    Call,
    CheckResult,
    Run,
    Verdict,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def run(session):
    run = Run(
        sentra_base_url="http://sentra.invalid",
        repeats=3,
        stichprobe_seed=1,
        stichprobe_anteil=0.0,
        label="Runde 1",
    )
    session.add(run)
    session.flush()
    return run


def _case(
    session,
    run,
    *,
    n=0,
    machine_flagged=False,
    human_says=None,
    schweregrad=1,
    grenzfall=False,
    kategorie=Kategorie.GO,
    repeats=1,
):
    case, version = case_store.create_case(
        session,
        kategorie=kategorie,
        ausgangsfrage=f"Frage {n}",
        erwartete_antwort="Erwartete Antwort.",
        referenz_korrekt="GOBT § 35",
        grenzfall=grenzfall,
    )
    case_store.approve(session, version)
    for repeat_index in range(repeats):
        call = Call(
            run_id=run.id,
            case_version_id=version.id,
            zweck=ZWECK_ANTWORT,
            status=OK,
            repeat_index=repeat_index,
            endpoint="/api/explorer/answer",
        )
        session.add(call)
        session.flush()
        session.add(
            CheckResult(
                call_id=call.id,
                pruefung="quellenauswahl",
                ergebnis=QUELLE_FALSCH if machine_flagged else QUELLE_KORREKT,
                auffaellig=machine_flagged,
            )
        )
    if human_says is not None:
        session.add(
            Verdict(
                run_id=run.id,
                case_version_id=version.id,
                tester="WD",
                gefunden_ueber="Stufe 2 (auffällig markiert)",
                kernbefunde={"original#0": "Befund."},
                quelle_4_3a="entfällt",
                quelle_4_3b=human_says,
                quelle_4_3c="Quelle stützt Aussage",
                schweregrad=schweregrad,
                reproduzierbar="einmalig",
                kisz_meldung=schweregrad >= 3,
            )
        )
    session.flush()
    return case, version


# ── The headline number ─────────────────────────────────────────────


class TestAgreement:
    def test_both_saying_the_source_was_wrong_is_agreement(self, session, run):
        _case(session, run, machine_flagged=True, human_says=QUELLE_FALSCH)

        assert report.agreement(session, run).einig == 1

    def test_both_saying_it_was_right_is_also_agreement(self, session, run):
        _case(session, run, machine_flagged=False, human_says=QUELLE_KORREKT)

        assert report.agreement(session, run).einig == 1

    def test_a_check_that_fired_and_was_wrong_says_too_strict(self, session, run):
        """Reviewer time spent on something that was fine."""
        _case(session, run, machine_flagged=True, human_says=QUELLE_KORREKT)

        found = report.agreement(session, run)

        assert found.zu_streng == 1
        assert found.zu_grosszuegig == 0

    def test_a_human_finding_what_the_check_missed_says_too_lenient(self, session, run):
        """The direction that matters most, and what Stufe 3 exists to surface."""
        _case(session, run, machine_flagged=False, human_says=QUELLE_FALSCH)

        found = report.agreement(session, run)

        assert found.zu_grosszuegig == 1
        assert found.zu_streng == 0

    def test_the_two_directions_are_never_conflated(self, session, run):
        """A single count of findings would report "2 disagreements" and say
        nothing about which way to move the threshold."""
        _case(session, run, n=1, machine_flagged=True, human_says=QUELLE_KORREKT)
        _case(session, run, n=2, machine_flagged=False, human_says=QUELLE_FALSCH)

        found = report.agreement(session, run)

        assert (found.zu_streng, found.zu_grosszuegig) == (1, 1)

    def test_an_unassessed_case_is_neither(self, session, run):
        """Counting it either way would move the headline number for a reason
        that has nothing to do with the threshold."""
        _case(session, run, machine_flagged=True, human_says=None)

        found = report.agreement(session, run)

        assert found.nicht_bewertet == 1
        assert found.bewertet == 0

    def test_a_round_nobody_assessed_has_no_rate_rather_than_zero(self, session, run):
        """0.0 would read as perfect agreement about a threshold nobody has
        checked, which is the most flattering possible lie."""
        _case(session, run, machine_flagged=True, human_says=None)

        assert report.agreement(session, run).abweichungsquote is None

    def test_the_quote_is_disagreements_over_assessed(self, session, run):
        _case(session, run, n=1, machine_flagged=True, human_says=QUELLE_KORREKT)
        _case(session, run, n=2, machine_flagged=True, human_says=QUELLE_FALSCH)
        _case(session, run, n=3, machine_flagged=False, human_says=QUELLE_KORREKT)
        _case(session, run, n=4, machine_flagged=False, human_says=QUELLE_KORREKT)

        assert report.agreement(session, run).abweichungsquote == 0.25


# ── The Phase-4 sheet ───────────────────────────────────────────────


class TestSheets:
    def test_one_sheet_per_case(self, session, run):
        _case(session, run, n=1, human_says=QUELLE_KORREKT)
        _case(session, run, n=2, human_says=QUELLE_KORREKT)

        assert len(report.sheets(session, run)) == 2

    def test_it_carries_the_human_assessment(self, session, run):
        _case(session, run, human_says=QUELLE_FALSCH, schweregrad=3)

        sheet = report.sheets(session, run)[0]

        assert sheet.quellenbewertung_4_3b == QUELLE_FALSCH
        assert sheet.schweregrad == 3
        assert sheet.tester == "WD"

    def test_the_machine_verdict_is_on_the_record(self, session, run):
        """Withheld from the queue while somebody is assessing; included here.
        A sheet that hid what the automation concluded would make the
        disagreement rate uncheckable by whoever receives it."""
        _case(session, run, machine_flagged=True, human_says=QUELLE_FALSCH)

        sheet = report.sheets(session, run)[0]

        assert sheet.ergebnis_automatikpruefung.startswith("auffällig")
        assert "quellenauswahl" in sheet.ergebnis_automatikpruefung

    def test_a_clean_case_says_unauffaellig(self, session, run):
        _case(session, run, machine_flagged=False, human_says=QUELLE_KORREKT)

        assert report.sheets(session, run)[0].ergebnis_automatikpruefung == "unauffällig"

    def test_the_techniques_reflect_what_was_actually_done(self, session, run):
        """4.1 because the round repeated, 4.4 because it is a Grenzfall, and
        not 4.2 because no paraphrases exist yet."""
        _case(session, run, grenzfall=True, human_says=QUELLE_KORREKT)

        techniques = report.sheets(session, run)[0].angewendete_techniken

        assert "4.1 Wiederholungslauf" in techniques
        assert "4.4 Grenzfall-Test" in techniques
        assert not any("4.2" in t for t in techniques)

    def test_an_unassessed_case_still_gets_a_sheet(self, session, run):
        """It went into the round, so it belongs in the round's documentation —
        with the human fields empty rather than the case missing."""
        _case(session, run, human_says=None)

        sheet = report.sheets(session, run)[0]

        assert sheet.test_id
        assert sheet.quellenbewertung_4_3b == ""
        assert sheet.manuell_geprueft_durch == "entfällt"

    def test_the_category_is_spelled_out(self, session, run):
        """A sheet going to KISZ should say Geschäftsordnung, not GO."""
        _case(session, run, human_says=QUELLE_KORREKT)

        assert report.sheets(session, run)[0].kategorie == "Geschäftsordnung"


# ── Across rounds ───────────────────────────────────────────────────


class TestTrend:
    def test_it_counts_cases_by_category(self, session, run):
        _case(session, run, n=1, kategorie=Kategorie.GO, human_says=QUELLE_KORREKT)
        _case(session, run, n=2, kategorie=Kategorie.GV, human_says=QUELLE_KORREKT)
        _case(session, run, n=3, kategorie=Kategorie.GO, human_says=QUELLE_KORREKT)

        found = report.trend(session)

        assert found.nach_kategorie["Geschäftsordnung"] == 2
        assert found.nach_kategorie["Gesetzgebungsverfahren"] == 1

    def test_it_counts_severities(self, session, run):
        _case(session, run, n=1, human_says=QUELLE_FALSCH, schweregrad=4)
        _case(session, run, n=2, human_says=QUELLE_FALSCH, schweregrad=1)

        assert report.trend(session).schweregrade == {1: 1, 4: 1}

    def test_it_counts_kisz_escalations(self, session, run):
        _case(session, run, n=1, human_says=QUELLE_FALSCH, schweregrad=3)
        _case(session, run, n=2, human_says=QUELLE_KORREKT, schweregrad=1)

        assert report.trend(session).kisz_meldungen == 1

    def test_it_says_where_findings_cluster(self, session, run):
        """ "Wo häufen sich Fußnotenfehler" is a group-by or it is somebody
        reading every sheet again."""
        _case(session, run, n=1, machine_flagged=True, human_says=QUELLE_FALSCH)
        _case(session, run, n=2, machine_flagged=True, human_says=QUELLE_FALSCH)

        assert report.trend(session).haeufigste_befunde["quellenauswahl"] == 2

    def test_a_case_flagged_on_every_repeat_is_one_finding(self, session, run):
        """#136. A CheckResult is written per call, so counting the rows scaled
        this with `repeats` — three findings reported beside `faelle: 1`, and
        two rounds run at different repeat counts not comparable, which is what
        a trend is for."""
        _case(session, run, n=1, machine_flagged=True, human_says=QUELLE_FALSCH, repeats=3)

        found = report.trend(session)

        assert found.faelle == 1
        assert found.haeufigste_befunde["quellenauswahl"] == 1

    def test_the_disagreement_rate_is_combined_over_rounds(self, session, run):
        _case(session, run, n=1, machine_flagged=True, human_says=QUELLE_KORREKT)
        _case(session, run, n=2, machine_flagged=False, human_says=QUELLE_KORREKT)

        found = report.trend(session)

        assert found.abweichung["zu_streng"] == 1
        assert found.abweichung["abweichungsquote"] == 0.5
