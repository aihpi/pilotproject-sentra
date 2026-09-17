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
    "gefunden_ueber": "Stufe 2 (auffällig markiert)",
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


def _round(client, *, grenzfall=False, repeats=2, handler=None):
    """An approved case, run, and its queue."""
    body = {
        "kategorie": "GO",
        "ausgangsfrage": "Wie lange darf ein Redner sprechen?",
        "erwartete_antwort": "15 Minuten nach § 35 GOBT.",
        "referenz_korrekt": "GOBT § 35",
        "referenz_korrekt_az": "WD 3 - 3000 - 029/23",
        "grenzfall": grenzfall,
    }
    test_id = client.post("/api/eval/cases", json=body).json()["test_id"]
    client.post(f"/api/eval/cases/{test_id}/freigeben")

    with session_scope() as session:
        run = runner.start_run(session, repeats=repeats)
        run_id = run.id
    runner.execute(run_id, _sentra(handler))

    return run_id, client.get(f"/api/eval/runs/{run_id}/queue").json()


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
    def test_it_is_recorded(self, client):
        _, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]

        response = client.post(f"/api/eval/calls/{call_id}/verdict", json=VERDICT)

        assert response.status_code == 201
        assert response.json()["tester"] == "Hotline / M. Schmidt"

    def test_the_machine_verdicts_survive_it(self, client):
        """The whole point. A human verdict that overwrote the machine one
        would destroy the only input to the disagreement rate."""
        _, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]
        before = client.get(f"/api/eval/calls/{call_id}/machine-verdicts").json()

        client.post(f"/api/eval/calls/{call_id}/verdict", json=VERDICT)

        after = client.get(f"/api/eval/calls/{call_id}/machine-verdicts").json()
        assert after == before

    def test_both_rows_exist_afterwards(self, client):
        _, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]
        client.post(f"/api/eval/calls/{call_id}/verdict", json=VERDICT)

        with session_scope() as session:
            assert session.execute(select(Verdict)).scalars().all()
            assert session.execute(select(CheckResult)).scalars().all()

    def test_the_queue_marks_it_assessed(self, client):
        run_id, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]
        client.post(f"/api/eval/calls/{call_id}/verdict", json=VERDICT)

        again = client.get(f"/api/eval/runs/{run_id}/queue").json()

        assert again[0]["assessed"] == 1
        assert [c["assessed"] for c in again[0]["calls"]] == [True, False]

    def test_a_second_verdict_is_refused(self, client):
        """Rejected rather than versioned: the first assessment is the one
        Stufe 1 is measured against."""
        _, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]
        client.post(f"/api/eval/calls/{call_id}/verdict", json=VERDICT)

        response = client.post(f"/api/eval/calls/{call_id}/verdict", json=VERDICT)

        assert response.status_code == 409
        assert "already assessed" in response.json()["detail"]

    def test_a_verdict_needs_an_author(self, client):
        """There is no authentication anywhere, so this is typed — and required,
        because a finding nobody has to own is a finding nobody follows up."""
        _, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]

        response = client.post(f"/api/eval/calls/{call_id}/verdict", json={**VERDICT, "tester": ""})

        assert response.status_code == 422

    @pytest.mark.parametrize("schweregrad", [0, 5, -1])
    def test_the_severity_scale_is_one_to_four(self, client, schweregrad):
        _, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]

        response = client.post(
            f"/api/eval/calls/{call_id}/verdict", json={**VERDICT, "schweregrad": schweregrad}
        )

        assert response.status_code == 422


# ── KISZ escalation ─────────────────────────────────────────────────


class TestKiszEscalation:
    @pytest.mark.parametrize("schweregrad", [3, 4])
    def test_erheblich_and_kritisch_escalate(self, client, schweregrad):
        run_id, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]

        body = client.post(
            f"/api/eval/calls/{call_id}/verdict", json={**VERDICT, "schweregrad": schweregrad}
        ).json()

        assert body["kisz_meldung"] is True
        assert len(client.get(f"/api/eval/runs/{run_id}/kisz").json()) == 1

    @pytest.mark.parametrize("schweregrad", [1, 2])
    def test_geringfuegig_and_moderat_do_not(self, client, schweregrad):
        run_id, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]

        body = client.post(
            f"/api/eval/calls/{call_id}/verdict", json={**VERDICT, "schweregrad": schweregrad}
        ).json()

        assert body["kisz_meldung"] is False
        assert client.get(f"/api/eval/runs/{run_id}/kisz").json() == []

    def test_escalation_does_not_depend_on_how_the_case_was_found(self, client):
        """Section 5: Schweregrad 3 and 4 go to KISZ whether the case arrived
        through Stufe 2 or the Stufe 3 sample."""
        run_id, queue = _round(client)
        call_id = queue[0]["calls"][0]["id"]

        body = client.post(
            f"/api/eval/calls/{call_id}/verdict",
            json={
                **VERDICT,
                "schweregrad": 4,
                "gefunden_ueber": "Stufe 3 (Stichprobe)",
            },
        ).json()

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
