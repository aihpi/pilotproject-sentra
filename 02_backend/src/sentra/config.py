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
    # 02_backend. compose and the k8s configmap both set the container
    # paths explicitly, so a /data default here buys nothing and only
    # breaks developer machines, where /data does not exist.
    documents_dir: str = "../03_data/Ausarbeitungen"
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
    feedback_file: str = "../03_data/feedback.jsonl"

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
