"""Approving only what can be measured (#257).

An ordinary case needs the Aktenzeichen of its correct source, and that
document has to be indexed in SENTRA. Otherwise 4.3b reports a wrong source
for a document SENTRA could never have cited, which reads as SENTRA failing
when the gap is in the corpus.
"""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sentra_eval import bestand, yaml_io
from sentra_eval import cases as case_store
from sentra_eval.app import create_app
from sentra_eval.categories import Kategorie
from sentra_eval.config import get_eval_settings
from sentra_eval.db import Base, get_engine

AZ = "WD 4 - 3000 - 115/22"

# Taken at import, before the conftest stub replaces it for each test.
_REAL_FETCH = bestand.fetch

INDEXIERT = bestand.Bestand(aktenzeichen=frozenset({"WD43000115/22"}))
LEER = bestand.Bestand()
WEG = bestand.Bestand(fehler="SENTRA ist nicht erreichbar, der Bestand kann nicht geprüft werden")


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _draft(session, **overrides):
    fields = {
        "ausgangsfrage": "Wird Dry Income besteuert?",
        "erwartete_antwort": "Ja, als Arbeitslohn.",
        "referenz_korrekt": "Mitarbeiterkapitalbeteiligungen, WD 4 - 3000 - 115/22",
        "referenz_korrekt_az": AZ,
    }
    fields.update(overrides)
    _, version = case_store.create_case(session, kategorie=Kategorie.FI, **fields)
    return version


class TestWhatBlocksApproval:
    def test_a_complete_case_with_an_indexed_source_has_nothing_in_the_way(self, session):
        assert case_store.approval_blockers(_draft(session), INDEXIERT) == []

    def test_the_aktenzeichen_is_required(self, session):
        version = _draft(session, referenz_korrekt_az="")

        assert case_store.approval_blockers(version, INDEXIERT) == [
            "Aktenzeichen der korrekten Quelle fehlt"
        ]

    def test_a_source_that_is_not_indexed_says_to_ingest_it(self, session):
        blockers = case_store.approval_blockers(_draft(session), LEER)

        assert blockers == [f"{AZ} ist nicht im Bestand, bitte erst einlesen"]

    def test_the_spelling_of_the_aktenzeichen_does_not_matter(self, session):
        version = _draft(session, referenz_korrekt_az="WD 4-3000-115/22")

        assert case_store.approval_blockers(version, INDEXIERT) == []

    def test_an_unreachable_sentra_blocks_rather_than_waves_through(self, session):
        assert case_store.approval_blockers(_draft(session), WEG) == [WEG.fehler]

    def test_a_grenzfall_needs_neither(self, session):
        """It has no correct source by definition, so there is nothing to look up."""
        version = _draft(session, referenz_korrekt="", referenz_korrekt_az="", grenzfall=True)

        assert case_store.approval_blockers(version, LEER) == []

    def test_everything_missing_is_listed_at_once(self, session):
        version = _draft(session, erwartete_antwort="", referenz_korrekt="", referenz_korrekt_az="")

        assert len(case_store.approval_blockers(version, INDEXIERT)) == 3

    def test_approve_refuses_with_the_blockers(self, session):
        version = _draft(session)

        with pytest.raises(case_store.IncompleteCase, match="nicht im Bestand"):
            case_store.approve(session, version, bestand=LEER)
        assert not version.is_approved


class TestAskingSentra:
    def _client(self, handler) -> httpx.Client:
        return httpx.Client(base_url="http://sentra", transport=httpx.MockTransport(handler))

    def test_it_reads_the_indexed_aktenzeichen(self):
        def handler(request):
            assert request.url.path == "/api/documents"
            return httpx.Response(200, json=[{"aktenzeichen": AZ}, {"aktenzeichen": ""}])

        found = _REAL_FETCH(self._client(handler))

        assert found.erreichbar
        assert found.enthaelt("WD 4 - 3000 - 115/22")
        assert not found.enthaelt("WD 5 - 3000 - 074/26")

    def test_an_error_becomes_an_unreachable_bestand(self):
        found = _REAL_FETCH(self._client(lambda request: httpx.Response(503)))

        assert not found.erreichbar
        assert "nicht erreichbar" in found.fehler


class TestTheApi:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JUDGE_BASE_URL", "http://judge.invalid/v1")
        monkeypatch.setenv("JUDGE_API_KEY", "not-a-real-key")
        monkeypatch.setenv("JUDGE_MODEL", "a-judge-that-is-not-the-chat-model")
        monkeypatch.setenv("CHAT_MODEL_UNDER_TEST", "llama-3-3-70b")
        monkeypatch.setenv("EVAL_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'eval.db'}")
        get_eval_settings.cache_clear()
        get_engine.cache_clear()
        Base.metadata.create_all(get_engine())
        monkeypatch.setattr(bestand, "fetch", lambda *a, **k: LEER)

        with TestClient(create_app()) as client:
            yield client

        get_eval_settings.cache_clear()
        get_engine.cache_clear()

    def _create(self, client):
        response = client.post(
            "/api/eval/cases",
            json={
                "kategorie": "FI",
                "ausgangsfrage": "Wird Dry Income besteuert?",
                "erwartete_antwort": "Ja.",
                "referenz_korrekt": "Quelle",
                "referenz_korrekt_az": AZ,
            },
        )
        assert response.status_code == 201
        return response.json()["test_id"]

    def test_the_listing_says_what_a_draft_still_needs(self, client):
        self._create(client)

        cases = client.get("/api/eval/cases").json()

        assert cases[0]["freigabe_hindernisse"] == [
            f"{AZ} ist nicht im Bestand, bitte erst einlesen"
        ]

    def test_the_button_is_refused_with_the_reason(self, client):
        test_id = self._create(client)

        response = client.post(f"/api/eval/cases/{test_id}/freigeben")

        assert response.status_code == 422
        assert "nicht im Bestand" in response.json()["detail"]


class TestImportingAFileThatApproves:
    def test_it_is_refused_when_the_source_is_not_indexed(self, session):
        entries = yaml_io.validate(
            [
                {
                    "kategorie": "FI",
                    "ausgangsfrage": "Wird Dry Income besteuert?",
                    "erwartete_antwort": "Ja.",
                    "referenz_korrekt": "Quelle",
                    "referenz_korrekt_az": AZ,
                    "status": "freigegeben",
                }
            ]
        )

        with pytest.raises(yaml_io.CaseFileError, match="nicht im Bestand"):
            yaml_io.apply(session, entries, bestand=LEER)
