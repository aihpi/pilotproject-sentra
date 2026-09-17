"""Tests that the settings actually reach the code that should honour them.

Two of these settings were declared and read by nobody, so the point here is not
that they parse but that changing them changes behaviour. Each test would have
passed vacuously before the wiring existed, so each one also asserts the path the
value travels.

Run:  uv run pytest tests/test_config_wiring.py -v
"""

import inspect

import pytest

from sentra.config import Settings
from sentra.rag.store import DimensionMismatch, _Collection
from sentra.services import ingest


def make_settings(**overrides) -> Settings:
    values = {"ai_hub_base_url": "https://hub.test/v1", "ai_hub_api_key": "k"}
    values.update(overrides)
    return Settings(_env_file=None, **values)


class TestCorsOrigins:
    def test_default_is_the_vite_dev_server(self):
        assert make_settings().cors_origins == ["http://localhost:5173"]

    def test_comma_separated_string(self):
        s = make_settings(cors_origins="http://a.test, http://b.test")
        assert s.cors_origins == ["http://a.test", "http://b.test"]

    def test_json_array(self):
        assert make_settings(cors_origins='["http://c.test"]').cors_origins == ["http://c.test"]

    def test_a_real_list_passes_through(self):
        assert make_settings(cors_origins=["http://d.test"]).cors_origins == ["http://d.test"]

    def test_blank_entries_are_dropped(self):
        assert make_settings(cors_origins="http://a.test,,  ").cors_origins == ["http://a.test"]


class TestChunkMaxTokens:
    def test_the_setting_reaches_the_chunker(self):
        """It was declared and never passed, so the call site is what matters."""
        source = inspect.getsource(ingest._run_ingestion_inner)
        assert "settings.chunk_max_tokens" in source

    def test_chunker_honours_the_limit(self):
        from sentra.domain import DocumentMetadata
        from sentra.ingestion.chunker import chunk_document

        meta = DocumentMetadata(
            aktenzeichen="WD 1 - 3000 - 001/25",
            fachbereich_number="WD 1",
            fachbereich="Test",
            document_type="Ausarbeitung",
            title="Test",
            completion_date="2025-01-01",
            language="de",
            source_file="test.pdf",
        )
        # One section far longer than a small limit, so it has to be split.
        body = "## Abschnitt\n\n" + "\n\n".join(["Ein Satz. " * 40] * 20)
        few = chunk_document(body, meta, max_tokens=4096)
        many = chunk_document(body, meta, max_tokens=64)
        assert len(many) > len(few), "a smaller token limit must produce more chunks"


class TestRetrievalTopK:
    def test_answer_request_defers_to_the_setting(self):
        from sentra.api.models import AnswerRequest

        assert AnswerRequest(query="x").top_k is None, (
            "top_k must be None by default so the router can substitute "
            "RETRIEVAL_TOP_K; a literal default here would shadow the setting"
        )

    def test_an_explicit_value_still_wins(self):
        from sentra.api.models import AnswerRequest

        assert AnswerRequest(query="x", top_k=3).top_k == 3

    def test_the_router_substitutes_the_setting(self):
        from sentra.api import routes

        for endpoint in (routes.explorer_answer, routes.explorer_overview):
            assert "settings.retrieval_top_k" in inspect.getsource(endpoint)

    def test_document_search_keeps_its_own_default(self):
        """It counts documents, not chunks, so it is not the same quantity."""
        from sentra.api.models import DocumentSearchRequest

        assert DocumentSearchRequest(query="x").top_k == 20


class FakeClient:
    """Reports a collection that exists with a fixed vector width."""

    def __init__(self, size: int | None):
        self._size = size

    def get_collections(self):
        class Named:
            name = "chunks"

        class Result:
            collections = [Named()] if self._size is not None else []

        return Result()

    def get_collection(self, collection_name: str):
        size = self._size

        class Vectors:
            pass

        v = Vectors()
        v.size = size

        class Params:
            vectors = v

        class Config:
            params = Params()

        class Info:
            config = Config()

        return Info()


def collection(size: int | None, configured: int = 4096) -> _Collection:
    return _Collection(FakeClient(size), "chunks", ("aktenzeichen",), configured)  # type: ignore[arg-type]


class TestPathDefaults:
    """Defaults must suit a host; containers override them.

    Both of these were container paths once, which made the feature fail
    wherever the app was run directly: /data does not exist on a developer
    machine, so the feedback endpoint answered 500 with a PermissionError.
    """

    @pytest.mark.parametrize("field", ["feedback_file", "documents_dir"])
    def test_not_an_unwritable_container_path(self, field):
        value = getattr(make_settings(), field)
        assert not value.startswith("/data"), (
            f"{field} defaults to {value!r}, a container path. compose and the "
            f"k8s configmap override these, so the default should be the one "
            f"that works when the app is run directly."
        )


class TestEmbeddingDimension:
    def test_default_matches_the_default_model(self):
        assert make_settings().embedding_dim == 4096

    def test_matching_width_is_accepted(self):
        collection(4096, configured=4096).verify_vector_size()

    def test_mismatch_is_refused(self):
        """The failure this exists for: the embedding model was changed."""
        with pytest.raises(DimensionMismatch) as exc:
            collection(1536, configured=4096).verify_vector_size()
        assert "1536" in str(exc.value) and "4096" in str(exc.value)

    def test_the_message_says_what_to_do(self):
        with pytest.raises(DimensionMismatch) as exc:
            collection(1536, configured=4096).verify_vector_size()
        message = str(exc.value)
        assert "EMBEDDING_DIM" in message
        assert "re-ingest" in message

    def test_absent_collection_is_not_a_mismatch(self):
        """Nothing to conflict with yet; ensure() will create it at our width."""
        collection(None, configured=4096).verify_vector_size()

    def test_the_setting_is_overridable(self):
        """Creation at that width is covered behaviourally in
        test_store_collection.py::TestEnsure."""
        assert make_settings(embedding_dim=1536).embedding_dim == 1536


class TestAiHubTimeouts:
    """Both clients get an explicit bound, and it is the configured one.

    Generation had no timeout at all, which left the openai client's own
    default of 600 seconds for reads. Measured against the live hub, an answer
    or an overview takes 20 to 29 seconds, so ten minutes is not a safety
    margin, it is a held worker and a spinner the user cannot escape: the
    frontend sets no timeout of its own and waits exactly as long as the
    backend does.
    """

    def test_generation_uses_the_configured_timeout(self):
        from sentra.rag.generator import AnswerGenerator

        settings = make_settings(generation_timeout_seconds=42.0)
        assert AnswerGenerator(settings)._client.timeout == 42.0

    def test_embedding_uses_the_configured_timeout(self):
        from sentra.rag.embeddings import EmbeddingClient

        settings = make_settings(embedding_timeout_seconds=17.0)
        assert EmbeddingClient(settings)._client.timeout == 17.0

    def test_neither_falls_back_to_the_library_default(self):
        """600 seconds is what the client uses when nobody says otherwise, so
        seeing it here would mean the setting is not reaching the client."""
        from sentra.rag.embeddings import EmbeddingClient
        from sentra.rag.generator import AnswerGenerator

        settings = make_settings()
        assert AnswerGenerator(settings)._client.timeout == 120.0
        assert EmbeddingClient(settings)._client.timeout == 60.0

    def test_generation_is_allowed_longer_than_embedding(self):
        """Not a style rule. Embedding one query takes about 0.2 seconds and a
        completion takes tens of seconds, so the same bound cannot suit both.
        """
        settings = make_settings()
        assert settings.generation_timeout_seconds > settings.embedding_timeout_seconds


class TestTheEnvFileIsShared:
    """backend/.env is read by SENTRA, the evaluation harness, compose and the
    tests. Each has to ignore the keys it does not own.

    This was a real failure rather than a hypothetical: adding the harness's
    JUDGE_* settings to that file made SENTRA refuse to start when run locally,
    while the container came up healthy — because unknown *environment
    variables* are ignored and unknown *dotenv keys* were not. The validation
    error also quoted each value back, which put an API key in a traceback.
    """

    def test_settings_ignores_keys_belonging_to_the_harness(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "AI_HUB_BASE_URL=http://hub.invalid/v1\n"
            "AI_HUB_API_KEY=not-a-real-key\n"
            "JUDGE_BASE_URL=http://judge.invalid/v1\n"
            "JUDGE_API_KEY=also-not-real\n"
            "JUDGE_MODEL=gpt-oss-120b\n"
            "CHAT_MODEL_UNDER_TEST=llama-3-3-70b\n",
            encoding="utf-8",
        )

        settings = Settings(_env_file=str(env_file))

        assert settings.ai_hub_base_url == "http://hub.invalid/v1"
        assert not hasattr(settings, "judge_model")

    def test_a_secret_it_does_not_own_never_reaches_an_error(self, tmp_path):
        """The failure mode worth keeping out: pydantic quotes offending values
        into the exception, so a forbidden JUDGE_API_KEY ended up in the
        traceback."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "AI_HUB_BASE_URL=http://hub.invalid/v1\n"
            "AI_HUB_API_KEY=not-a-real-key\n"
            "JUDGE_API_KEY=sk-should-never-appear-anywhere\n",
            encoding="utf-8",
        )

        settings = Settings(_env_file=str(env_file))  # does not raise

        assert "should-never-appear" not in repr(settings)
