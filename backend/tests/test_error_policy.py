"""What a failed request answers, per dependency.

The router used to hold three policies at once: /documents turned any
exception into an empty list, /health turned it into "degraded", and the five
explorer endpoints turned it into a 500 with a stack trace. The frontend could
not tell "nothing found" from "nothing working", which is the distinction
these tests pin.

Offline. Every failure is injected through a stub dependency, so no Qdrant and
no AI Hub, and the exceptions raised are the real classes those two libraries
raise, taken from watching them fail for real.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import APIConnectionError, AuthenticationError, RateLimitError
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from sentra.api.errors import register_error_handlers
from sentra.api.routes import get_embedder, get_generator, get_store, router
from sentra.config import get_settings
from sentra.rag.store import DimensionMismatch


def qdrant_down() -> Exception:
    return ResponseHandlingException("connection refused")


def qdrant_refuses() -> Exception:
    return UnexpectedResponse(
        status_code=404, reason_phrase="Not Found", content=b"not found", headers=None
    )


def hub_down() -> Exception:
    return APIConnectionError(request=None)  # type: ignore[arg-type]


def hub_rejects_key() -> Exception:
    import httpx

    response = httpx.Response(401, request=httpx.Request("POST", "http://hub/v1/embeddings"))
    return AuthenticationError("bad key", response=response, body=None)


def hub_rate_limits() -> Exception:
    import httpx

    response = httpx.Response(429, request=httpx.Request("POST", "http://hub/v1/embeddings"))
    return RateLimitError("slow down", response=response, body=None)


class Raises:
    """Any attribute access returns a callable that raises the given error."""

    def __init__(self, error: Exception):
        self._error = error

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise self._error

        return fail


class WorkingEmbedder:
    """Succeeds, so a test about Qdrant is not really a test about the AI Hub.

    The explorer endpoints embed the query before they search, so an embedder
    that raises short-circuits every one of them.
    """

    def embed_query(self, query: str) -> list[float]:
        return [0.0, 1.0]


class WorkingGenerator:
    def generate_answer(self, question: str, context: str, system_prompt=None) -> str:
        return "eine Antwort"

    def generate_overview(self, topic: str, context: str, system_prompt=None) -> str:
        return "ein Überblick"


class EmptyStore:
    """A store whose collection exists but holds nothing."""

    def collection_exists(self) -> bool:
        return True

    def collection_info(self) -> dict:
        return {"points_count": 0}


class NoCollectionStore:
    """Before the first ingestion: nothing has been created yet."""

    def collection_exists(self) -> bool:
        return False


@pytest.fixture
def client_factory(settings):
    """A client with chosen dependencies, and the policy registered."""

    def make(store=None, embedder=None, generator=None):
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(router)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_store] = lambda: store or EmptyStore()
        app.dependency_overrides[get_embedder] = lambda: embedder or WorkingEmbedder()
        app.dependency_overrides[get_generator] = lambda: generator or WorkingGenerator()
        return TestClient(app, raise_server_exceptions=False)

    return make


SEARCH_ENDPOINTS = [
    ("/api/explorer/documents", {"query": "x"}),
    ("/api/explorer/similar", {"aktenzeichen": "WD 2 - 3000 - 001/20"}),
    ("/api/explorer/sources", {"query": "x"}),
    ("/api/explorer/answer", {"query": "x"}),
    ("/api/explorer/overview", {"query": "x"}),
]


class TestQdrantUnavailable:
    """Was a 500 with a stack trace on the explorer endpoints."""

    @pytest.mark.parametrize(("path", "body"), SEARCH_ENDPOINTS)
    def test_explorer_endpoints_answer_503(self, client_factory, path, body):
        client = client_factory(store=Raises(qdrant_down()))
        response = client.post(path, json=body)

        assert response.status_code == 503
        assert "Suchdatenbank" in response.json()["detail"]

    @pytest.mark.parametrize(
        "error", [qdrant_down(), qdrant_refuses()], ids=["unreachable", "refusing"]
    )
    def test_both_qdrant_failure_kinds(self, client_factory, error):
        client = client_factory(store=Raises(error))
        assert client.post("/api/explorer/documents", json={"query": "x"}).status_code == 503


class TestAiHubUnavailable:
    @pytest.mark.parametrize(
        "error",
        [hub_down(), hub_rejects_key(), hub_rate_limits()],
        ids=["unreachable", "bad key", "rate limited"],
    )
    def test_answer_endpoint_answers_503(self, client_factory, error):
        client = client_factory(embedder=Raises(error))
        response = client.post("/api/explorer/answer", json={"query": "x"})

        assert response.status_code == 503
        assert "KI-Dienst" in response.json()["detail"]


class TestMisconfigured:
    def test_dimension_mismatch_answers_503(self, client_factory):
        client = client_factory(store=Raises(DimensionMismatch("4096 vs 1024")))
        response = client.post("/api/explorer/documents", json={"query": "x"})

        assert response.status_code == 503
        assert "konfiguriert" in response.json()["detail"]


class TestDocumentsTellsEmptyFromDown:
    """The change the frontend can actually observe."""

    def test_no_collection_yet_is_an_empty_list(self, client_factory):
        """Before the first ingestion. Genuinely nothing indexed, not an error,
        so the UI can say so rather than showing a failure."""
        response = client_factory(store=NoCollectionStore()).get("/api/documents")

        assert response.status_code == 200
        assert response.json() == []

    def test_empty_collection_is_an_empty_list(self, client_factory):
        response = client_factory(store=EmptyStore()).get("/api/documents")

        assert response.status_code == 200
        assert response.json() == []

    def test_unreachable_qdrant_is_no_longer_an_empty_list(self, client_factory):
        """This is what used to be indistinguishable from the two above."""
        response = client_factory(store=Raises(qdrant_down())).get("/api/documents")

        assert response.status_code == 503


class TestRequestErrorsStayRequestErrors:
    """HTTPException passes through the handlers untouched.

    The detail is asserted as well as the status, because the frontend now
    displays it rather than substituting a message of its own. That makes
    these strings user-facing, and they are German for the same reason every
    other message the user sees is.
    """

    def test_dot_dot_in_the_name_is_400(self, client_factory):
        """Encoded slashes never reach the handler, they fail to match the
        route, so the guard that matters is the one on "..".
        """
        response = client_factory().get("/api/documents/..evil.pdf")
        assert response.status_code == 400
        assert response.json()["detail"] == "Ungültiger Dateiname."

    def test_non_pdf_is_400(self, client_factory):
        response = client_factory().get("/api/documents/notes.txt")
        assert response.status_code == 400
        assert response.json()["detail"] == "Es werden nur PDF-Dateien ausgeliefert."

    def test_missing_document_is_404(self, client_factory):
        """Reachable from the UI: a document whose file was deleted is still
        listed until something removes it from the index, so clicking its PDF
        lands here.
        """
        response = client_factory().get("/api/documents/nicht-vorhanden.pdf")
        assert response.status_code == 404
        assert response.json()["detail"] == "Dokument nicht gefunden."

    def test_malformed_body_is_422(self, client_factory):
        assert client_factory().post("/api/explorer/documents", json={}).status_code == 422


class TestDetailsAreGerman:
    def test_every_user_reachable_detail(self, client_factory):
        """One English detail is left on purpose, the ingest 409, because the
        frontend overrides that status with its own wording and a German twin
        here would be the same sentence in two places.
        """
        client = client_factory()
        details = [
            client.get("/api/documents/..evil.pdf").json()["detail"],
            client.get("/api/documents/notes.txt").json()["detail"],
            client.get("/api/documents/nicht-vorhanden.pdf").json()["detail"],
            client_factory(store=Raises(qdrant_down()))
            .post("/api/explorer/documents", json={"query": "x"})
            .json()["detail"],
        ]
        english = [d for d in details if "not found" in d or "Invalid" in d or "only" in d.lower()]
        assert not english, f"English text reaches the UI: {english}"


class TestUnexpectedErrorsStay500:
    """A bug must not be dressed up as a dependency outage: 503 invites a
    retry, and retrying a bug just fails again."""

    def test_a_plain_error_is_500(self, client_factory):
        client = client_factory(store=Raises(ValueError("something we did not foresee")))
        assert client.post("/api/explorer/documents", json={"query": "x"}).status_code == 500


class TestHealthIsExempt:
    """Deliberately keeps its own policy.

    An endpoint whose job is reporting on dependencies is useless if it fails
    when they do, and the k8s liveness, readiness and startup probes all read
    it.
    """

    def test_reports_degraded_rather_than_503(self, client_factory):
        response = client_factory(store=Raises(qdrant_down())).get("/api/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert "error" in body["qdrant"]

    def test_reports_healthy_when_reachable(self, client_factory):
        response = client_factory(store=EmptyStore()).get("/api/health")

        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestFeedbackDiskFailure:
    def test_unwritable_path_is_503_not_500(self, client_factory, settings, tmp_path):
        """Was an unhandled OSError, so a full disk answered 500 with a
        traceback. Reproduced here by pointing the file at a directory."""
        blocked = tmp_path / "in-the-way"
        blocked.mkdir()
        app_settings = settings.model_copy(update={"feedback_file": str(blocked)})

        app = FastAPI()
        register_error_handlers(app)
        app.include_router(router)
        app.dependency_overrides[get_settings] = lambda: app_settings
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/feedback",
            json={"question": "q", "answer": "a", "rating": "positive", "comment": None},
        )

        assert response.status_code == 503
        assert "Rückmeldung" in response.json()["detail"]
