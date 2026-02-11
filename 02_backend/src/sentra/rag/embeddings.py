import logging

from openai import OpenAI

from sentra.config import Settings

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Client for generating embeddings via the AI Model Hub (OpenAI-compatible API)."""

    def __init__(self, settings: Settings) -> None:
        self._client = OpenAI(
            base_url=settings.ai_hub_base_url,
            api_key=settings.ai_hub_api_key,
        )
        self._model = settings.embedding_model
        self._batch_size = settings.embedding_batch_size

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document texts.

        Applies the "- " prefix required by Octen-Embedding-8B (Qwen3 upstream quirk)
        to ensure consistent document embedding behavior.

        Processes in batches to avoid API timeouts on large inputs.
        """
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            prefixed = ["- " + text for text in batch]

            response = self._client.embeddings.create(
                input=prefixed,
                model=self._model,
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

            logger.debug(
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
