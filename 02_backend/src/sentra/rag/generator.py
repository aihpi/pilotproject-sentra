import logging
from collections.abc import Iterator

from openai import OpenAI

from sentra.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Du bist ein Assistent der Wissenschaftlichen Dienste des Deutschen Bundestages.

Regeln:
- Beantworte die Frage ausschließlich auf Basis der bereitgestellten Kontextauszüge.
- Wenn der Kontext die Frage nicht ausreichend beantwortet, sage dies ehrlich.
- Gib immer die Quellen (Aktenzeichen und Abschnittstitel) an, auf die du dich beziehst.
- Antworte auf Deutsch, es sei denn, der Nutzer fragt auf Englisch.
- Fasse die relevanten Informationen strukturiert zusammen.
- Erfinde keine Informationen, die nicht im Kontext enthalten sind.\
"""


def format_context(results: list[dict]) -> str:
    """Format retrieved chunks into a context string for the LLM."""
    parts = []
    for r in results:
        header = f"[Quelle: {r['aktenzeichen']}, Abschnitt: {r['section_title']}]"
        parts.append(f"{header}\n{r['text']}")
    return "\n\n---\n\n".join(parts)


class AnswerGenerator:
    """Generate answers from retrieved context using an LLM."""

    def __init__(self, settings: Settings) -> None:
        self._client = OpenAI(
            base_url=settings.ai_hub_base_url,
            api_key=settings.ai_hub_api_key,
        )
        self._model = settings.chat_model

    def generate(self, question: str, context: str) -> str:
        """Generate a complete answer (non-streaming)."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Kontext:\n{context}\n\nFrage: {question}",
                },
            ],
            temperature=0.1,
            max_tokens=2048,
        )
        return response.choices[0].message.content or ""

    def generate_stream(self, question: str, context: str) -> Iterator[str]:
        """Generate an answer with streaming (yields text chunks)."""
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Kontext:\n{context}\n\nFrage: {question}",
                },
            ],
            temperature=0.1,
            max_tokens=2048,
            stream=True,
        )

        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
