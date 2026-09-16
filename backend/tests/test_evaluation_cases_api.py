"""The case endpoints, over HTTP.

Against a temporary SQLite file rather than Postgres, so these run in CI. The
schema comes from the same models; the migrations that build it on Postgres are
covered in test_evaluation_migrations.py.

What is worth testing at this level, over and above the store's own tests, is
the part a caller can get wrong: that PATCH does the right thing without being
told which thing to do. Editing an approved version is not an error the caller
has to handle — it is a request for a new draft, and that is what comes back.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentra.evaluation.config import get_eval_settings
from sentra.evaluation.db import Base, get_engine
from sentra.main import mount_evaluation

CASE = {
    "kategorie": "GO",
    "ausgangsfrage": "Wie lange darf ein Redner im Plenum sprechen?",
    "abteilung": "Hotline",
    "erwartete_antwort": "Grundsatz 15 Minuten je Fraktion nach § 35 GOBT.",
    "referenz_korrekt": "GOBT § 35",
    "referenz_falsch": "GOBT § 35 a. F.",
}


@pytest.fixture
def client(monkeypatch, tmp_path, settings):
    monkeypatch.setenv("JUDGE_BASE_URL", "http://judge.invalid/v1")
    monkeypatch.setenv("JUDGE_API_KEY", "not-a-real-key")
    monkeypatch.setenv("JUDGE_MODEL", "a-judge-that-is-not-the-chat-model")
    monkeypatch.setenv("EVAL_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'eval.db'}")
    get_eval_settings.cache_clear()
    get_engine.cache_clear()

    Base.metadata.create_all(get_engine())

    app = FastAPI()
    mount_evaluation(app, settings.model_copy(update={"eval_enabled": True}))
    yield TestClient(app)

    get_eval_settings.cache_clear()
    get_engine.cache_clear()


class TestCreating:
    def test_a_case_comes_back_with_an_allocated_test_id(self, client):
        response = client.post("/api/eval/cases", json=CASE)

        assert response.status_code == 201
        assert response.json()["test_id"] == "TF-GO-001"

    def test_it_starts_as_one_draft_version(self, client):
        body = client.post("/api/eval/cases", json=CASE).json()

        assert len(body["versions"]) == 1
        assert body["versions"][0]["status"] == "entwurf"

    def test_a_question_is_required(self, client):
        response = client.post("/api/eval/cases", json={**CASE, "ausgangsfrage": ""})

        assert response.status_code == 422

    def test_an_unknown_category_is_rejected(self, client):
        """The closed list, enforced at the edge rather than trusted."""
        response = client.post("/api/eval/cases", json={**CASE, "kategorie": "XX"})

        assert response.status_code == 422


class TestReading:
    def test_listing(self, client):
        client.post("/api/eval/cases", json=CASE)
        client.post("/api/eval/cases", json=CASE)

        assert len(client.get("/api/eval/cases").json()) == 2

    def test_an_unknown_test_id_is_a_404(self, client):
        response = client.get("/api/eval/cases/TF-GO-999")

        assert response.status_code == 404
        assert "nicht gefunden" in response.json()["detail"]

    def test_the_categories_are_served_for_the_dropdown(self, client):
        body = client.get("/api/eval/kategorien").json()

        assert body["GO"] == "Geschäftsordnung"


class TestEditing:
    def test_a_draft_is_edited_in_place(self, client):
        client.post("/api/eval/cases", json=CASE)

        body = client.patch(
            "/api/eval/cases/TF-GO-001", json={"erwartete_antwort": "Anders"}
        ).json()

        assert len(body["versions"]) == 1
        assert body["versions"][0]["erwartete_antwort"] == "Anders"

    def test_editing_an_approved_case_adds_a_version(self, client):
        client.post("/api/eval/cases", json=CASE)
        client.post("/api/eval/cases/TF-GO-001/freigeben")

        body = client.patch(
            "/api/eval/cases/TF-GO-001", json={"erwartete_antwort": "Überarbeitet"}
        ).json()

        assert [v["version"] for v in body["versions"]] == [1, 2]
        assert body["versions"][1]["status"] == "entwurf"

    def test_the_approved_version_keeps_what_it_had(self, client):
        client.post("/api/eval/cases", json=CASE)
        client.post("/api/eval/cases/TF-GO-001/freigeben")

        body = client.patch(
            "/api/eval/cases/TF-GO-001", json={"erwartete_antwort": "Überarbeitet"}
        ).json()

        assert body["versions"][0]["erwartete_antwort"] == CASE["erwartete_antwort"]


class TestApproving:
    def test_approving_stamps_the_timestamp(self, client):
        client.post("/api/eval/cases", json=CASE)

        body = client.post("/api/eval/cases/TF-GO-001/freigeben").json()

        assert body["versions"][0]["status"] == "freigegeben"
        assert body["versions"][0]["freigegeben_at"] is not None

    def test_an_incomplete_case_is_refused_with_a_reason(self, client):
        client.post("/api/eval/cases", json={**CASE, "erwartete_antwort": ""})

        response = client.post("/api/eval/cases/TF-GO-001/freigeben")

        assert response.status_code == 422
        assert "erwartete Antwort" in response.json()["detail"]


class TestWithdrawing:
    def test_a_withdrawn_case_leaves_the_list(self, client):
        client.post("/api/eval/cases", json=CASE)
        client.post("/api/eval/cases/TF-GO-001/zurueckziehen")

        assert client.get("/api/eval/cases").json() == []

    def test_and_its_number_stays_spent(self, client):
        client.post("/api/eval/cases", json=CASE)
        client.post("/api/eval/cases/TF-GO-001/zurueckziehen")

        body = client.post("/api/eval/cases", json=CASE).json()

        assert body["test_id"] == "TF-GO-002"
