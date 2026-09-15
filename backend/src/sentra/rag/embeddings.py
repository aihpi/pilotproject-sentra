import logging
import time

from openai import OpenAI

from sentra.config import Settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = [1, 2, 4]


class EmbeddingClient:
    """Client for generating embeddings via the AI Model Hub (OpenAI-compatible API)."""

    def __init__(self, settings: Settings) -> None:
        self._client = OpenAI(
            base_url=settings.ai_hub_base_url,
            api_key=settings.ai_hub_api_key,
            timeout=60.0,
        )
        self._model = settings.embedding_model
        self._batch_size = settings.embedding_batch_size

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document texts.

        Applies the "- " prefix required by Octen-Embedding-8B (Qwen3 upstream quirk)
        to ensure consistent document embedding behavior.

        Processes in batches with retry logic for transient API failures.
        """
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            prefixed = ["- " + text for text in batch]

            batch_embeddings = self._embed_with_retry(prefixed)
            all_embeddings.extend(batch_embeddings)

            logger.info(
                "Embedded batch %d-%d / %d",
                i,
                min(i + self._batch_size, len(texts)),
                len(texts),
            )

        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text.

        No prefix is applied for queries — only documents get the "- " prefix.
        """
        response = self._client.embeddings.create(
            input=text,
            model=self._model,
        )
        return response.data[0].embedding

    def _embed_with_retry(self, texts: list[str]) -> list[list[float]]:
        """Call the embedding API with retry and exponential backoff."""
        for attempt in range(MAX_RETRIES):
            try:
                response = self._client.embeddings.create(
                    input=texts,
                    model=self._model,
                )
                return [item.embedding for item in response.data]
            except Exception:
                if attempt == MAX_RETRIES - 1:
                    raise
                wait = RETRY_BACKOFF_SECONDS[attempt]
                logger.warning(
                    "Embedding API call failed (attempt %d/%d), retrying in %ds",
                    attempt + 1,
                    MAX_RETRIES,
                    wait,
                    exc_info=True,
                )
                time.sleep(wait)
        raise RuntimeError("Unreachable")  # satisfy type checker
