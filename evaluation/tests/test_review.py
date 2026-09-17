"""Stufe 2: the queue, and what a human decided.

Everything here serves one number. Section 6 of the Vorlage names the
disagreement rate between the automatic verdict and the human one as the most
important measurement in the process — it is what says whether the Stufe-1
threshold is too loose or too strict, which is the thing being calibrated.

Two properties protect it, and they are what most of these tests are about:

  - the queue carries no machine verdicts. Not hidden by the UI — absent from
    the response. If they were in it, one careless render would turn the
    headline metric into a measure of anchoring.
  - a human verdict never overwrites a machine one. Overwriting would leave
    nothing to compare.
"""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sentra_eval import runner
from sentra_eval.app import create_app
from sentra_eval.config import get_eval_settings
from sentra_eval.db import Base, get_engine, session_scope
from sentra_eval.models import CheckResult, Verdict

ANSWER = {
    "text": "Nach § 35 GOBT gilt eine Redezeit von 15 Minuten [1].",
    "sources": [{"aktenzeichen": "WD 3 - 3000 - 029/23", "title": "Redezeit"}],
    "system_prompt": "Du bist ein Assistent ...",
    "finish_reason": "stop",
    "model": "llama-3-3-70b",
}

VERDICT = {
    "tester": "Hotline / M. Schmidt",
    "kernbefunde": {"original#0": "Antwort korrekt.", "original#1": "Identisch."},
    "quelle_4_3a": "entfällt",
    "quelle_4_3b": "korrekte Quelle",
    "quelle_4_3c": "Quelle stützt Aussage",
    "schweregrad": 1,
    "reproduzierbar": "einmalig",
    "anmerkung": "",
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("JUDGE_BASE_URL", "http://judge.invalid/v1")
    monkeypatch.setenv("JUDGE_API_KEY", "not-a-real-key")
    monkeypatch.setenv("JUDGE_MODEL", "a-judge-that-is-not-the-chat-model")
    monkeypatch.setenv("CHAT_MODEL_UNDER_TEST", "llama-3-3-70b")
    monkeypatch.setenv("SENTRA_BASE_URL", "http://sentra.invalid")
    monkeypatch.setenv("EVAL_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'review.db'}")
    get_eval_settings.cache_clear()
    get_engine.cache_clear()
    Base.metadata.create_all(get_engine())

    with TestClient(create_app()) as c:
        yield c

    get_eval_settings.cache_clear()
    get_engine.cache_clear()


def _sentra(handler=None):
    def default(request: httpx.Request) -> httpx.Response:
        if "documents" in str(request.url):
            return httpx.Response(
                200, json={"documents": [{"aktenzeichen": "WD 3 - 3000 - 029/23"}]}
            )
        return httpx.Response(200, json=ANSWER)

    return httpx.Client(
        transport=httpx.MockTransport(handler or default), base_url="http://sentra.invalid"
    )


def _round(client, *, grenzfall=False, repeats=2, handler=None, clean=False):
    """An approved case, run, and its queue.

    Flagged by default. Triage only queues cases a human has to look at, so a
    case that passes every check does not appear — which is the point of Stufe
    1 and would make these tests about the queue's contents inspect an empty
    list. The flag comes from the reference Aktenzeichen not matching what the
    stubbed answer cites, which is a real 4.3b finding rather than a fixture
    trick. `clean=True` is for the tests that are about triage filtering.
    """
    body = {
        "kategorie": "GO",
        "ausgangsfrage": "Wie lange darf ein Redner sprechen?",
        "erwartete_antwort": "15 Minuten nach § 35 GOBT.",
        "referenz_korrekt": "GOBT § 35",
        "referenz_korrekt_az": ("WD 3 - 3000 - 029/23" if clean else "WD 9 - 3000 - 999/25"),
        "grenzfall": grenzfall,
    }
    test_id = client.post("/api/eval/cases", json=body).json()["test_id"]
    client.post(f"/api/eval/cases/{test_id}/freigeben")

    with session_scope() as session:
        # Seeded explicitly so a test never depends on a random draw.
        run = runner.start_run(session, repeats=repeats, stichprobe_seed=1, stichprobe_anteil=0.0)
        run_id = run.id
    runner.execute(run_id, _sentra(handler))

    return run_id, client.get(f"/api/eval/runs/{run_id}/queue").json()


def _submit(client, run_id, entry, **overrides):
    """One Phase-4 sheet for a case."""
    return client.post(
        f"/api/eval/runs/{run_id}/cases/{entry['case_version_id']}/verdict",
        json={**VERDICT, **overrides},
    )


# ── The queue ───────────────────────────────────────────────────────


class TestTheQueue:
    def test_it_lists_the_cases_with_their_answers(self, client):
        _, queue = _round(client)

        assert len(queue) == 1
        assert len(queue[0]["calls"]) == 2

    def test_it_carries_the_yardstick(self, client):
        """The expected answer and the reference sources, beside the answer, so
        a reviewer is not comparing from memory."""
        _, queue = _round(client)

        assert queue[0]["erwartete_antwort"] == "15 Minuten nach § 35 GOBT."
        assert queue[0]["referenz_korrekt"] == "GOBT § 35"

    def test_it_does_not_carry_machine_verdicts(self, client):
        """The property the headline metric rests on. Absent from the response,
        not hidden by the screen — otherwise one careless render turns the
        Stufe-1-versus-human comparison into a measure of anchoring."""
        _, queue = _round(client)

        serialised = str(queue)
        assert "quellenauswahl" not in serialised
        assert "auffaellig" not in serialised
        assert "ergebnis" not in serialised

    def test_and_the_checks_really_did_run(self, client):
        """So the previous test is about omission rather than about there being
        nothing to omit."""
        _round(client)

        with session_scope() as session:
            assert session.execute(select(CheckResult)).scalars().all()

    def test_the_recall_probe_is_not_in_the_queue(self, client):
        """It is not an answer under test. Showing it would ask a reviewer to
        assess a document search."""
        _, queue = _round(client)

        assert all(c["text"] for c in queue[0]["calls"])
        assert len(queue[0]["calls"]) == 2

    def test_a_grenzfall_is_labelled_as_always_manual(self, client):
        """4.4: never filtered out of review, so it says so from the start
        rather than depending on what triage later decides."""
        _, queue = _round(client, grenzfall=True)

        assert queue[0]["gefunden_ueber"] == "Grenzfall (immer manuell, 4.4)"

    def test_failed_calls_are_not_queued(self, client):
        """There is nothing for a human to assess in a 503."""

        def broken(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "kaputt"})

        _, queue = _round(client, handler=broken)

        assert queue == []


# ── Machine verdicts, on request only ───────────────────────────────


class TestMachineVerdicts:
    def test_they_are_available_from_their_own_endpoint(self, client):
        _, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]

        body = client.get(f"/api/eval/calls/{call_id}/machine-verdicts").json()

        assert {c["pruefung"] for c in body["per_call"]} == {
            "quellenauswahl",
            "marker_ausrichtung",
            "ablehnung",
            "abschneidung",
        }

    def test_the_group_verdict_comes_with_them(self, client):
        """4.1's repeat comparison is about the group, so it arrives alongside
        rather than pretending to be about this one call."""
        _, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]

        body = client.get(f"/api/eval/calls/{call_id}/machine-verdicts").json()

        assert [c["pruefung"] for c in body["per_group"]] == ["wiederholbarkeit"]

    def test_an_unknown_call_is_a_404(self, client):
        response = client.get(
            "/api/eval/calls/00000000-0000-0000-0000-000000000000/machine-verdicts"
        )

        assert response.status_code == 404


# ── Verdicts ────────────────────────────────────────────────────────


class TestSubmittingAVerdict:
    def test_one_sheet_covers_the_whole_case(self, client):
        """Section 6 is "Dokumentation je Testfall": one sheet for the case,
        with a Kernbefund per answer inside it — not one sheet per answer."""
        run_id, queue = _round(client, repeats=3)

        response = _submit(client, run_id, queue[0])

        assert response.status_code == 201
        assert len(queue[0]["calls"]) == 3

    def test_the_per_answer_findings_are_kept(self, client):
        run_id, queue = _round(client)

        body = _submit(client, run_id, queue[0]).json()

        assert body["kernbefunde"]["original#0"] == "Antwort korrekt."

    def test_reproduzierbar_is_now_answerable(self, client):
        """It asks whether a finding recurred across the repeats. Against a
        single call it was a question the row could not answer."""
        run_id, queue = _round(client, repeats=3)

        body = _submit(client, run_id, queue[0], reproduzierbar="wiederholt").json()

        assert body["reproduzierbar"] == "wiederholt"

    def test_the_machine_verdicts_survive_it(self, client):
        """A human verdict that overwrote the machine one would destroy the
        only input to the disagreement rate."""
        run_id, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]
        before = client.get(f"/api/eval/calls/{call_id}/machine-verdicts").json()

        _submit(client, run_id, queue[0])

        assert client.get(f"/api/eval/calls/{call_id}/machine-verdicts").json() == before

    def test_both_rows_exist_afterwards(self, client):
        run_id, queue = _round(client)
        _submit(client, run_id, queue[0])

        with session_scope() as session:
            assert session.execute(select(Verdict)).scalars().all()
            assert session.execute(select(CheckResult)).scalars().all()

    def test_the_queue_marks_the_case_assessed(self, client):
        run_id, queue = _round(client)
        _submit(client, run_id, queue[0])

        again = client.get(f"/api/eval/runs/{run_id}/queue").json()

        assert again[0]["assessed"] is True

    def test_a_second_sheet_for_the_same_case_is_refused(self, client):
        """The first assessment is the one Stufe 1 is measured against."""
        run_id, queue = _round(client)
        _submit(client, run_id, queue[0])

        response = _submit(client, run_id, queue[0])

        assert response.status_code == 409
        assert "already assessed" in response.json()["detail"]

    def test_a_verdict_needs_an_author(self, client):
        run_id, queue = _round(client)

        assert _submit(client, run_id, queue[0], tester="").status_code == 422

    @pytest.mark.parametrize("schweregrad", [0, 5, -1])
    def test_the_severity_scale_is_one_to_four(self, client, schweregrad):
        run_id, queue = _round(client)

        assert _submit(client, run_id, queue[0], schweregrad=schweregrad).status_code == 422

    def test_an_unknown_case_is_a_404(self, client):
        run_id, _ = _round(client)

        response = client.post(
            f"/api/eval/runs/{run_id}/cases/00000000-0000-0000-0000-000000000000/verdict",
            json=VERDICT,
        )

        assert response.status_code == 404


class TestGefundenUeberIsDerived:
    """How a case reached a reviewer is half of what the trend report measures,
    so the server decides it rather than the form asserting it."""

    def test_the_client_cannot_set_it(self, client):
        run_id, queue = _round(client)

        body = _submit(client, run_id, queue[0], gefunden_ueber="Stufe 3 (Stichprobe)").json()

        assert body["gefunden_ueber"] == "Stufe 2 (auffällig markiert)"

    def test_a_grenzfall_is_recorded_as_always_manual(self, client):
        """4.4: never filtered out of review, whatever triage later decides."""
        run_id, queue = _round(client, grenzfall=True)

        body = _submit(client, run_id, queue[0]).json()

        assert body["gefunden_ueber"] == "Grenzfall (immer manuell, 4.4)"


# ── KISZ escalation ─────────────────────────────────────────────────


class TestKiszEscalation:
    @pytest.mark.parametrize("schweregrad", [3, 4])
    def test_erheblich_and_kritisch_escalate(self, client, schweregrad):
        run_id, queue = _round(client)

        body = _submit(client, run_id, queue[0], schweregrad=schweregrad).json()

        assert body["kisz_meldung"] is True
        assert len(client.get(f"/api/eval/runs/{run_id}/kisz").json()) == 1

    @pytest.mark.parametrize("schweregrad", [1, 2])
    def test_geringfuegig_and_moderat_do_not(self, client, schweregrad):
        run_id, queue = _round(client)

        body = _submit(client, run_id, queue[0], schweregrad=schweregrad).json()

        assert body["kisz_meldung"] is False
        assert client.get(f"/api/eval/runs/{run_id}/kisz").json() == []

    def test_escalation_does_not_depend_on_how_the_case_was_found(self, client):
        """Section 5: Schweregrad 3 and 4 go to KISZ whether the case arrived
        through Stufe 2 or the Stufe 3 sample."""
        run_id, queue = _round(client, grenzfall=True)

        body = _submit(client, run_id, queue[0], schweregrad=4).json()

        assert body["kisz_meldung"] is True


# ── The form's vocabulary ───────────────────────────────────────────


class TestVorlageOptions:
    def test_the_lists_are_the_vorlages_wording(self, client):
        """Served rather than copied into the frontend, for the reason #37 gave
        about prompts: two copies drift, and this one has to keep matching a
        paper form."""
        body = client.get("/api/eval/vorlage-optionen").json()

        assert body["quelle_4_3a"] == [
            "existiert & stimmt überein",
            "weicht ab",
            "existiert nicht",
            "entfällt",
        ]
        assert body["quelle_4_3c"] == ["Quelle stützt Aussage", "stützt Aussage nicht"]
        assert body["schweregrad"]["4"] == "kritisch"


# ── Phase 4, over HTTP ──────────────────────────────────────────────


class TestTheReportEndpoints:
    """Exercised through the API, not only as functions.

    Two report endpoints shipped in an earlier task referencing a module the
    router had not imported. The tests passed because nothing called them, and
    ruff caught it — these make the tests catch it too.
    """

    def test_the_sheets_come_back(self, client):
        run_id, queue = _round(client)

        response = client.get(f"/api/eval/runs/{run_id}/boegen")

        assert response.status_code == 200
        assert response.json()[0]["test_id"] == "TF-GO-001"

    def test_a_sheet_carries_the_machine_verdict(self, client):
        """Withheld from the queue, present in the record."""
        run_id, _ = _round(client)

        sheet = client.get(f"/api/eval/runs/{run_id}/boegen").json()[0]

        assert sheet["ergebnis_automatikpruefung"].startswith("auffällig")

    def test_the_disagreement_rate_comes_back(self, client):
        run_id, _ = _round(client)

        response = client.get(f"/api/eval/runs/{run_id}/abweichung")

        assert response.status_code == 200
        # Nothing assessed yet, so there is no rate rather than a flattering zero.
        assert response.json()["abweichungsquote"] is None

    def test_the_rate_appears_once_somebody_assesses(self, client):
        run_id, queue = _round(client)

        _submit(client, run_id, queue[0], quelle_4_3b="falsche bzw. veraltete Quelle")

        body = client.get(f"/api/eval/runs/{run_id}/abweichung").json()
        assert body["einig"] == 1
        assert body["abweichungsquote"] == 0.0

    def test_the_trend_report_comes_back(self, client):
        _round(client)

        response = client.get("/api/eval/trend")

        assert response.status_code == 200
        assert response.json()["runden"] >= 1

    def test_the_triage_summary_comes_back(self, client):
        run_id, _ = _round(client)

        body = client.get(f"/api/eval/runs/{run_id}/triage").json()

        assert body["gesamt"] == 1
        assert body["stufe_2"] == 1
