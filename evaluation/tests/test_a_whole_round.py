"""A round driven the way an operator drives one, end to end.

Every other test in this suite builds its state directly: a helper calls
`create_case`, adds a `Call`, writes a `CheckResult`, and the assertions run
over rows the test put there. That is fast and precise, and it is how three
bugs stayed invisible behind a green suite.

  #130  the fixture approved a Grenzfall with `referenz_korrekt="y"`.
        A real Grenzfall has no reference, and could not be approved at all —
        so technique 4.4 could not run in any round, and 197 tests passed over
        a check that was unreachable.

  #132  `_abgelehnt` was exercised on a single call. A round makes three, and
        the other two took a path that recorded a verdict by the rule #109
        had discarded.

  #136  `_case` built one call per case. A round at `repeats: 3` builds three,
        and the trend was counting rows, so one finding was reported as three.

The common shape is not missing assertions. It is a fixture that can construct
states the application cannot, and cannot construct states the application
does. So this module asserts nothing about rows. It writes a case file, imports
it, runs the round and reads what an operator reads: the review queue, the
Phase-4 sheets, the trend.

Offline, on purpose. SENTRA is an `httpx.MockTransport` and the judge is
stubbed, so this runs on every CI run rather than skipping wherever there are
no credentials — the point is a test whose *setup* is the operator's path, not
a test that needs the real services.

If you add a helper here, the rule that matters: it must not be able to build
something the application would refuse.
"""

import httpx
import pytest
from sqlalchemy.orm import Session

from sentra_eval import report, runner, triage, yaml_io
from sentra_eval.config import get_eval_settings
from sentra_eval.db import Base, get_engine

# Written the way cases/beispiel.yaml says to write one: the Grenzfall has no
# reference, because the corpus holds no document that answers it. That single
# empty field is what #130 made impossible.
CASE_FILE = """
- kategorie: GO
  ausgangsfrage: Wie hoch ist die Mondtagegeldpauschale für Dienstreisen zum Mars?
  abteilung: Hotline
  erwartete_antwort: Keine Antwort. Der Bestand enthält nichts dazu.
  referenz_korrekt: ""
  referenz_korrekt_az: ""
  grund_fuer_aufnahme: Grenzfall-Test 4.4.
  grenzfall: true
  status: freigegeben

- kategorie: GO
  ausgangsfrage: Wie lange darf ein Redner im Plenum sprechen?
  abteilung: Hotline
  erwartete_antwort: 15 Minuten je Fraktion nach § 35 GOBT.
  referenz_korrekt: GOBT § 35
  referenz_korrekt_az: WD 3 - 3000 - 029/23
  grenzfall: false
  status: freigegeben

# Answered from the wrong source, every time. A round needs one case that
# actually fails a per-call check, or anything counting findings is being
# asserted about an empty table — which is how #136 survived the first draft
# of this module.
- kategorie: GO
  ausgangsfrage: Wie viele Mitglieder hat der Ältestenrat?
  abteilung: Hotline
  erwartete_antwort: 23 Mitglieder nach § 6 GOBT.
  referenz_korrekt: GOBT § 6
  referenz_korrekt_az: WD 3 - 3000 - 099/23
  grenzfall: false
  status: freigegeben
"""

MARS = "Mars"
AZ = "WD 3 - 3000 - 029/23"

HEDGE = (
    "Die bereitgestellten Kontextauszüge enthalten keine Informationen dazu. "
    "Daher kann ich auf Basis der bereitgestellten Informationen keine Antwort geben."
)
ANSWER = "Nach § 35 GOBT gilt eine Redezeit von 15 Minuten je Fraktion [1]."


@pytest.fixture
def db(monkeypatch, tmp_path):
    monkeypatch.setenv("EVAL_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'round.db'}")
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


@pytest.fixture
def sentra():
    """SENTRA as it actually behaves: it hedges in prose on the Mars question
    rather than returning the literal refusal, because vector search always
    returns the top k however irrelevant. That is the behaviour #109 was
    decided about, and the reason this is not a string comparison."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "documents" in str(request.url):
            return httpx.Response(200, json={"documents": [{"aktenzeichen": AZ}]})
        frage = request.read().decode()
        if MARS in frage:
            return httpx.Response(200, json={"text": HEDGE, "sources": [{"aktenzeichen": AZ}]})
        # The Ältestenrat question is answered from AZ too, which is not the
        # source the case expects — a wrong-source finding on every repeat.
        return httpx.Response(
            200, json={"text": ANSWER, "sources": [{"aktenzeichen": AZ, "title": "Redezeit"}]}
        )

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://sentra.invalid")


@pytest.fixture(autouse=True)
def judge(monkeypatch):
    """Stubbed on the text, not on the call count, so the round's own decision
    about *when* to ask is left to the code under test."""
    from sentra_eval import judge as judge_module

    def beurteile(text, *, frage):
        return text.strip() == HEDGE, "gestubbt"

    monkeypatch.setattr(judge_module, "beurteile_ablehnung", beurteile)
    monkeypatch.setattr(judge_module, "compare", lambda *a, **k: (True, "identisch", ""))


@pytest.fixture
def round_done(session, sentra):
    """Import a case file and run a round over it. Three repeats, because one
    repeat cannot tell a per-call bug from a per-case one."""
    entries = yaml_io.parse(CASE_FILE)
    imported = yaml_io.apply(session, entries)
    session.commit()

    run = runner.start_run(session, label="Ganzer Durchlauf", repeats=3)
    session.commit()
    runner.execute(run.id, sentra)
    session.expire_all()
    return imported, run


class TestTheFileBecomesARound:
    def test_every_case_is_imported_and_approved(self, round_done):
        """Including the Grenzfall, which is the case #130 could not approve —
        and an unapproved case is never planned, so 4.4 never ran."""
        imported, _run = round_done

        assert len(imported.created) == 3
        assert len(imported.approved) == 3

    def test_the_round_completes(self, session, round_done):
        _imported, run = round_done

        assert runner.outstanding(session, run) == []

    def test_the_expectations_predate_the_round(self, session, round_done):
        """The Vorlage's rule, and the one the whole record rests on: an answer
        measured against an expectation written after it proves nothing."""
        _imported, run = round_done

        assert runner.audit_is_sound(session, run) is True


class TestWhatTheReviewerSees:
    def test_the_grenzfall_is_always_in_front_of_a_human(self, session, round_done):
        """Never filtered out, whatever the checks said. 4.4 is where the real
        risk sits, so the Vorlage keeps Grenzfälle out of automated filtering."""
        _imported, run = round_done

        entries = {t.case_version_id: t for t in triage.triage_run(session, run)}
        grenzfall = [t for t in entries.values() if "Grenzfall" in (t.gefunden_ueber or "")]

        assert len(grenzfall) == 1

    def test_a_correctly_refused_grenzfall_is_not_flagged_as_a_defect(self, session, round_done):
        """It is reviewed because it is a Grenzfall, not because anything went
        wrong. Before #132 it arrived with `ablehnung` flagged on two of its
        three repeats, which is the noise #109 set out to stop."""
        _imported, run = round_done

        entries = [t for t in triage.triage_run(session, run) if t.gefunden_ueber]
        grenzfall = next(t for t in entries if "Grenzfall" in t.gefunden_ueber)

        assert "ablehnung" not in grenzfall.auffaellige_pruefungen

    def test_the_ordinary_case_is_not_sent_for_review(self, session, round_done):
        """It cited the right source and did not hedge, so nothing should send
        it to a reviewer except the Stufe-3 sample, which this round did not
        draw. Note the Grenzfall has no flagged checks either — it is in the
        queue for being a Grenzfall, not for being wrong, and conflating the
        two is how a clean Grenzfall starts reading as a defect."""
        _imported, run = round_done

        entries = triage.triage_run(session, run)
        ordinary = [t for t in entries if not t.needs_review]

        assert len(ordinary) == 1
        assert ordinary[0].auffaellige_pruefungen == ()


class TestTheSheetsAndTheTrend:
    def test_one_sheet_per_case_not_per_call(self, session, round_done):
        _imported, run = round_done

        assert len(report.sheets(session, run)) == 3

    def test_the_sheet_records_the_techniques_actually_applied(self, session, round_done):
        """4.4 appears only because a Grenzfall ran. That is the end-to-end
        statement #130 made false: the technique was implemented, tested and
        unreachable."""
        _imported, run = round_done

        grenzfall = next(s for s in report.sheets(session, run) if MARS in s.urspruenglicher_prompt)

        assert "4.4 Grenzfall-Test" in grenzfall.angewendete_techniken

    def test_the_trend_counts_cases_on_one_denominator(self, session, round_done):
        """#136. Every finding here is per case, so nothing in the table may
        scale with `repeats` — otherwise two rounds run at different repeat
        counts cannot be compared, which is what a trend is for."""
        _imported, _run = round_done

        found = report.trend(session)

        # One case cited the wrong source, on each of its three repeats.
        assert found.faelle == 3
        assert found.haeufigste_befunde["quellenauswahl"] == 1

    def test_nobody_has_reviewed_yet_so_there_is_no_rate(self, session, round_done):
        """The headline metric is Stufe 1 against a human, and with no human
        verdicts it has to be absent rather than zero. Zero would read as
        perfect agreement."""
        _imported, run = round_done

        assert report.agreement(session, run).abweichungsquote is None
