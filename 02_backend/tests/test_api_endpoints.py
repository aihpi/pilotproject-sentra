"""API contract tests using FastAPI TestClient.

These verify the HTTP layer: correct status codes, response schemas,
and error handling — what the frontend actually receives.

The tests use the real app with real settings. Endpoints that need
Qdrant/AI Hub are marked as integration tests.

Run:  uv run pytest tests/test_api_endpoints.py -v -m integration
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentra.api.routes import get_embedder, get_generator, get_store, router
from sentra.config import get_settings
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.generator import AnswerGenerator
from sentra.rag.store import VectorStore

pytestmark = pytest.mark.integration

app = FastAPI()
app.include_router(router)


@pytest.fixture(scope="module")
def client(settings):
    """TestClient with real settings and shared clients injected."""
    store = VectorStore(settings)
    embedder = EmbeddingClient(settings)
    generator = AnswerGenerator(settings)

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_embedder] = lambda: embedder
    app.dependency_overrides[get_generator] = lambda: generator

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Health endpoint ────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_200(self, client, require_qdrant):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["qdrant"] == "connected"

    def test_health_includes_collection_info(self, client, require_qdrant):
        data = client.get("/api/health").json()
        assert data["collection"] is not None
        assert "points_count" in data["collection"]
        assert data["collection"]["points_count"] > 0


# ── Document listing endpoint ──────────────────────────────────────


class TestDocumentListEndpoint:
    def test_returns_200(self, client, require_qdrant):
        response = client.get("/api/documents")
        assert response.status_code == 200

    def test_returns_list(self, client, require_qdrant):
        data = client.get("/api/documents").json()
        assert isinstance(data, list)
        assert len(data) > 0, "Document list is empty"

    def test_document_has_required_fields(self, client, require_qdrant):
        """Every document in the list must have the fields the frontend expects."""
        data = client.get("/api/documents").json()
        required_fields = {
            "aktenzeichen", "title", "fachbereich_number", "fachbereich",
            "document_type", "completion_date", "language", "source_file",
        }
        for doc in data:
            missing = required_fields - set(doc.keys())
            assert not missing, (
                f"Document {doc.get('aktenzeichen', '?')} missing fields: {missing}"
            )

    def test_returns_expected_count(self, client, require_qdrant):
        """We have 17 PDFs; after ingestion, all should be listed."""
        from tests.conftest import TOTAL_PDFS
        data = client.get("/api/documents").json()
        assert len(data) == TOTAL_PDFS, (
            f"Expected {TOTAL_PDFS} documents, got {len(data)}"
        )


# ── Document serving endpoint ──────────────────────────────────────


class TestDocumentServingEndpoint:
    def test_serves_existing_pdf(self, client, require_qdrant):
        """Should serve a known PDF file."""
        response = client.get("/api/documents/WD 3-029-23.pdf")
        assert response.status_code == 200
        assert "application/pdf" in response.headers.get("content-type", "")

    def test_404_for_nonexistent_file(self, client, require_qdrant):
        response = client.get("/api/documents/NONEXISTENT.pdf")
        assert response.status_code == 404

    def test_rejects_path_traversal(self, client, require_qdrant):
        """Path traversal must not serve arbitrary files. FastAPI normalizes
        '../' out of URLs, so the handler sees just 'passwd' → 400 (non-PDF).
        For direct '..' in path params, the route returns 400."""
        response = client.get("/api/documents/..%2F..%2Fetc%2Fpasswd")
        assert response.status_code in (400, 404), (
            f"Path traversal attempt returned {response.status_code}, expected 400 or 404"
        )

    def test_400_for_non_pdf(self, client, require_qdrant):
        response = client.get("/api/documents/secrets.txt")
        assert response.status_code == 400


# ── Explorer: Documents by topic ───────────────────────────────────


class TestExplorerDocumentsEndpoint:
    def test_returns_200(self, client, require_qdrant):
        response = client.post("/api/explorer/documents", json={
            "query": "Verfassung und Verwaltung",
        })
        assert response.status_code == 200

    def test_response_schema(self, client, require_qdrant):
        data = client.post("/api/explorer/documents", json={
            "query": "Gesundheit",
        }).json()
        assert "documents" in data
        assert isinstance(data["documents"], list)
        if data["documents"]:
            doc = data["documents"][0]
            assert "aktenzeichen" in doc
            assert "title" in doc
            assert "relevance_score" in doc
            assert "source_file" in doc

    def test_with_filters(self, client, require_qdrant):
        data = client.post("/api/explorer/documents", json={
            "query": "Recht",
            "fachbereich": "WD 3",
            "date_range": {"date_from": "2023", "date_to": "2023"},
        }).json()
        for doc in data["documents"]:
            fb = doc["aktenzeichen"].split(" - ")[0].strip()
            assert fb == "WD 3"

    def test_empty_query_still_works(self, client, require_qdrant):
        """An empty-ish query should not crash the server."""
        response = client.post("/api/explorer/documents", json={
            "query": "a",
        })
        assert response.status_code == 200


# ── Explorer: Similar documents ────────────────────────────────────


class TestExplorerSimilarEndpoint:
    def test_returns_200(self, client, require_qdrant):
        response = client.post("/api/explorer/similar", json={
            "aktenzeichen": "WD 3 - 3000 - 029/23",
        })
        assert response.status_code == 200

    def test_response_schema(self, client, require_qdrant):
        data = client.post("/api/explorer/similar", json={
            "aktenzeichen": "WD 3 - 3000 - 029/23",
        }).json()
        assert "documents" in data


# ── Explorer: External sources ─────────────────────────────────────


class TestExplorerSourcesEndpoint:
    def test_returns_200(self, client, require_qdrant):
        response = client.post("/api/explorer/sources", json={
            "query": "Recht und Gesetz",
        })
        assert response.status_code == 200

    def test_response_schema(self, client, require_qdrant):
        data = client.post("/api/explorer/sources", json={
            "query": "Umwelt Naturschutz",
        }).json()
        assert "sources" in data
        assert isinstance(data["sources"], list)
        if data["sources"]:
            src = data["sources"][0]
            assert "url" in src
            assert "cited_in" in src


# ── Explorer: Answer endpoint ──────────────────────────────────────


class TestExplorerAnswerEndpoint:
    def test_returns_200(self, client, require_qdrant):
        response = client.post("/api/explorer/answer", json={
            "query": "Was ist Grundgesetz?",
        })
        assert response.status_code == 200

    def test_response_schema(self, client, require_qdrant):
        data = client.post("/api/explorer/answer", json={
            "query": "Was ist Arbeitsrecht?",
        }).json()
        assert "text" in data
        assert "sources" in data
        assert "system_prompt" in data
        assert len(data["text"]) > 0

    def test_custom_prompt_accepted(self, client, require_qdrant):
        custom = "Antworte nur mit Ja oder Nein."
        data = client.post("/api/explorer/answer", json={
            "query": "Gibt es Regelungen zum Datenschutz?",
            "system_prompt": custom,
        }).json()
        assert data["system_prompt"] == custom


# ── Explorer: Overview endpoint ────────────────────────────────────


class TestExplorerOverviewEndpoint:
    def test_returns_200(self, client, require_qdrant):
        response = client.post("/api/explorer/overview", json={
            "query": "Umweltpolitik in Deutschland",
        })
        assert response.status_code == 200

    def test_response_schema(self, client, require_qdrant):
        data = client.post("/api/explorer/overview", json={
            "query": "Europäische Integration",
        }).json()
        assert "text" in data
        assert "sources" in data
        assert "system_prompt" in data
