from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    collection_name: str = "bundestag_documents"

    # Ingestion
    documents_dir: str = "/data/Ausarbeitungen"
    chunk_max_tokens: int = 2048
    embedding_batch_size: int = 32

    # RAG
    retrieval_top_k: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
