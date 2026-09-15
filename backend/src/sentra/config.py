from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # AI Model Hub
    ai_hub_base_url: str
    ai_hub_api_key: str

    # Model names (as shown in AI Hub)
    # How long to wait on the AI Hub before giving up. Both were measured
    # against the live hub rather than guessed: embedding one query takes about
    # 0.2s, and generating an answer or an overview 20 to 29 seconds over six
    # samples. The values leave roughly 4x headroom over the slowest.
    #
    # Generation had no value at all, which left the openai client's own
    # default of 600 seconds for reads. That is ten minutes of a held worker
    # for a request someone is watching a spinner for, and the frontend sets
    # no timeout of its own, so the browser waits exactly as long as we do.
    #
    # A timeout that fires raises APITimeoutError, an OpenAIError, so the
    # handler in api/errors.py already turns it into a 503.
    embedding_timeout_seconds: float = 60.0
    generation_timeout_seconds: float = 120.0

    embedding_model: str = "octen-embedding-8b"
    chat_model: str = "llama-3-3-70b"

    # Vector width the embedding model produces. Changing embedding_model almost
    # certainly means changing this too, and a collection built at one width
    # cannot serve vectors of another, so startup checks the two agree.
    embedding_dim: int = 4096

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    collection_name: str = "bundestag_documents"
    doc_collection_name: str = "bundestag_doc_summaries"

    # Ingestion
    # Paths default to what works when the app is run directly from
    # backend. compose and the k8s configmap both set the container
    # paths explicitly, so a /data default here buys nothing and only
    # breaks developer machines, where /data does not exist.
    documents_dir: str = "../data/Ausarbeitungen"
    chunk_max_tokens: int = 2048
    embedding_batch_size: int = 32

    # How many chunks to retrieve for a generated answer when the request does
    # not say. Document search and similar-document lookups have their own
    # defaults, because they count documents rather than chunks.
    retrieval_top_k: int = 10

    # Origins allowed to call the API from a browser. Only the vite dev server
    # needs this: under docker compose nginx proxies /api, so the browser sees a
    # single origin and CORS never applies. Accepts a comma-separated list.
    # NoDecode: without it pydantic-settings tries to JSON-parse the value
    # before the validator below ever sees it, so a plain comma-separated
    # string raises instead of being split.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # Feedback
    feedback_file: str = "../data/feedback.jsonl"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept CORS_ORIGINS as a comma-separated string or a JSON array."""
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                import json

                return json.loads(raw)
            return [part.strip() for part in raw.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
