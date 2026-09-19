"""What an answer says about itself when asked, and what it does not say otherwise.

Three things SENTRA had and threw away: the chunks it retrieved, whether the
model finished or hit its ceiling, and which model the hub actually ran. All
three matter to anything judging an answer — a truncated answer reads as an
inconsistent one unless you can see `finish_reason`, and a claim cannot be
checked against the context if the context is gone.

The test that carries the most weight is the one asserting the response is
unchanged without the flag. This payload is the entire retrieved context; adding
it to every answer would make the explorer's responses several times larger for
a UI that never displays them.

Offline. The store, embedder and generator are stubs, so no Qdrant and no hub.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentra.api.routes import get_embedder, get_generator, get_store, router
from sentra.config import get_settings
from sentra.domain import Generation, Hit

ENDPOINTS = ["/api/explorer/answer", "/api/explorer/overview"]


def _hit(index: int = 0, aktenzeichen: str = "WD 3 - 3000 - 029/23") -> Hit:
    return Hit(
        score=0.9 - index / 100,
        text=f"Der Text von Abschnitt {index}.",
        section_title=f"Abschnitt {index}",
        section_path=str(index),
        chunk_index=index,
        aktenzeichen=aktenzeichen,
        fachbereich_number="WD 3",
        fachbereich="Verfassung",
        document_type="Sachstand",
        title="Ein Dokument",
        completion_date="2023-05-01",
        language="de",
        source_file="WD 3-029-23.pdf",
    )


class StoreWithHits:
    def __init__(self, hits: list[Hit]) -> None:
        self._hits = hits

    def search(self, **kwargs) -> list[Hit]:
        return self._hits


class Embedder:
    def embed_query(self, query: str) -> list[float]:
        return [0.0, 1.0]


class Generator:
    """Reports what the hub would have said, including the parts SENTRA used
    to discard."""

    def __init__(self, finish_reason: str = "stop", model: str = "llama-3-3-70b") -> None:
        self._finish_reason = finish_reason
        self._model = model

    def generate_answer(self, question, context, system_prompt=None) -> Generation:
        return Generation("Eine Antwort [1].", self._finish_reason, self._model)

    def generate_overview(self, topic, context, system_prompt=None) -> Generation:
        return Generation("Ein Überblick [1].", self._finish_reason, self._model)


@pytest.fixture
def client_factory(settings):
    def make(hits=None, generator=None):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_store] = lambda: StoreWithHits(
            hits if hits is not None else [_hit(0), _hit(1)]
        )
        app.dependency_overrides[get_embedder] = lambda: Embedder()
        app.dependency_overrides[get_generator] = lambda: generator or Generator()
        return TestClient(app)

    return make


# ── Without the flag, nothing changed ───────────────────────────────


class TestTheDefaultResponseIsUntouched:
    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_the_payload_is_absent(self, client_factory, path):
        body = client_factory().post(path, json={"query": "Redezeit"}).json()

        assert "hits" not in body
        assert "finish_reason" not in body
        assert "model" not in body

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_the_keys_are_exactly_what_they_were(self, client_factory, path):
        """The frontend parses this. A new key is a change to a contract even
        when nothing breaks on it today."""
        body = client_factory().post(path, json={"query": "Redezeit"}).json()

        assert set(body) == {"text", "sources", "system_prompt"}

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_the_prompt_is_still_reported(self, client_factory, path):
        """The route sets response_model_exclude_none to keep the debug fields
        out, which drops any null field. system_prompt is always populated, so
        nothing a caller reads today disappears — this is what says so."""
        body = client_factory().post(path, json={"query": "Redezeit"}).json()

        assert body["system_prompt"]

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_the_prompt_survives_the_refusal_path_too(self, client_factory, path):
        """The no-results path also sets it, which is what makes provenance
        per call work without a side table."""
        body = client_factory(hits=[]).post(path, json={"query": "Unbekannt"}).json()

        assert body["system_prompt"]

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_debug_false_is_the_same_as_omitting_it(self, client_factory, path):
        omitted = client_factory().post(path, json={"query": "Redezeit"}).json()
        explicit = client_factory().post(path, json={"query": "Redezeit", "debug": False}).json()

        assert omitted == explicit


# ── With the flag ───────────────────────────────────────────────────


class TestTheDebugPayload:
    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_the_retrieved_chunks_come_back(self, client_factory, path):
        body = client_factory().post(path, json={"query": "Redezeit", "debug": True}).json()

        assert len(body["hits"]) == 2
        assert body["hits"][0]["text"] == "Der Text von Abschnitt 0."

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_a_chunk_carries_what_a_check_needs(self, client_factory, path):
        body = client_factory().post(path, json={"query": "Redezeit", "debug": True}).json()

        assert set(body["hits"][0]) == {
            "aktenzeichen",
            "section_title",
            "chunk_index",
            "score",
            "text",
            # Since #183. A check asking whether a claim is supported by the
            # cited passage needs the passage, and the exact range rather than
            # the source card's single best-matching page.
            "page_from",
            "page_to",
            "paragraph_from",
            "paragraph_to",
        }

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_the_finish_reason_comes_back(self, client_factory, path):
        body = client_factory().post(path, json={"query": "Redezeit", "debug": True}).json()

        assert body["finish_reason"] == "stop"

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_truncation_is_visible(self, client_factory, path):
        """Überblick generates at 3072 tokens and Fachfrage at 2048. Without
        this, an answer cut off at the ceiling is indistinguishable from one
        the model chose to end, and gets filed as an inconsistency."""
        client = client_factory(generator=Generator(finish_reason="length"))

        body = client.post(path, json={"query": "Redezeit", "debug": True}).json()

        assert body["finish_reason"] == "length"

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_the_served_model_comes_back(self, client_factory, path):
        """CHAT_MODEL is a name we send. This is what answered."""
        client = client_factory(generator=Generator(model="llama-3-3-70b-instruct-v2"))

        body = client.post(path, json={"query": "Redezeit", "debug": True}).json()

        assert body["model"] == "llama-3-3-70b-instruct-v2"

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_the_answer_itself_is_the_same(self, client_factory, path):
        """Asking for the payload must not change what is being measured."""
        plain = client_factory().post(path, json={"query": "Redezeit"}).json()
        debug = client_factory().post(path, json={"query": "Redezeit", "debug": True}).json()

        assert debug["text"] == plain["text"]
        assert debug["sources"] == plain["sources"]


# ── The refusal path ────────────────────────────────────────────────


class TestNoResults:
    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_the_refusal_is_unchanged(self, client_factory, path):
        """4.4 checks for this string exactly. Nothing here may touch it."""
        body = client_factory(hits=[]).post(path, json={"query": "Unbekannt"}).json()

        assert body["text"] == "Es wurden keine relevanten Dokumente gefunden."
        assert body["sources"] == []

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_the_refusal_is_unchanged_with_debug(self, client_factory, path):
        client = client_factory(hits=[])

        body = client.post(path, json={"query": "Unbekannt", "debug": True}).json()

        assert body["text"] == "Es wurden keine relevanten Dokumente gefunden."
        assert body["sources"] == []
        assert body["hits"] == []

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_no_model_was_called_so_there_is_no_finish_reason(self, client_factory, path):
        """Nothing generated, so reporting "stop" would be a lie about a call
        that never happened."""
        client = client_factory(hits=[])

        body = client.post(path, json={"query": "Unbekannt", "debug": True}).json()

        assert "finish_reason" not in body
        assert "model" not in body
