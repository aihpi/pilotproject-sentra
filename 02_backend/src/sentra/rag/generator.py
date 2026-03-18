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

# UC#10 – Fachfrage: concise, direct answer with numbered source refs
FACHFRAGE_PROMPT = """\
Du bist ein Assistent der Wissenschaftlichen Dienste des Deutschen Bundestages.

Beantworte die folgende Fachfrage präzise und direkt auf Basis der bereitgestellten \
Kontextauszüge.

Regeln:
- Gib eine klare, fokussierte Antwort auf die konkrete Frage.
- Verwende nummerierte Quellenverweise **[1]**, **[2]** usw. im Text.
- Jede Quellennummer bezieht sich auf das Aktenzeichen der jeweiligen Quelle \
(in der Reihenfolge ihres ersten Auftretens).
- Wenn der Kontext die Frage nicht ausreichend beantwortet, sage dies ehrlich.
- Antworte auf Deutsch.
- Erfinde keine Informationen, die nicht im Kontext enthalten sind.
- Halte die Antwort kompakt (max. 3–4 Absätze).\
"""

# UC#2 – Themenüberblick: structured overview with sections
OVERVIEW_PROMPT = """\
Du bist ein Assistent der Wissenschaftlichen Dienste des Deutschen Bundestages.

Erstelle einen strukturierten Überblick zum folgenden Thema auf Basis der \
bereitgestellten Kontextauszüge.

Regeln:
- Gliedere die Antwort mit Markdown-Überschriften (##, ###).
- Organisiere die Informationen thematisch, nicht nach Quellen.
- Verwende nummerierte Quellenverweise **[1]**, **[2]** usw. im Text.
- Jede Quellennummer bezieht sich auf das Aktenzeichen der jeweiligen Quelle \
(in der Reihenfolge ihres ersten Auftretens).
- Beginne mit einer kurzen Zusammenfassung des aktuellen Stands.
- Erfinde keine Informationen, die nicht im Kontext enthalten sind.
- Antworte auf Deutsch.\
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
        return self._complete(
            SYSTEM_PROMPT,
            f"Kontext:\n{context}\n\nFrage: {question}",
        )

    def generate_stream(self, question: str, context: str) -> Iterator[str]:
        """Generate an answer with streaming (yields text chunks)."""
        return self._stream(
            SYSTEM_PROMPT,
            f"Kontext:\n{context}\n\nFrage: {question}",
        )

    def generate_answer(
        self, question: str, context: str, system_prompt: str | None = None,
    ) -> str:
        """Generate a focused answer for a Fachfrage (UC#10)."""
        return self._complete(
            system_prompt or FACHFRAGE_PROMPT,
            f"Kontext:\n{context}\n\nFrage: {question}",
        )

    def generate_answer_stream(
        self, question: str, context: str, system_prompt: str | None = None,
    ) -> Iterator[str]:
        """Stream a focused answer for a Fachfrage (UC#10)."""
        return self._stream(
            system_prompt or FACHFRAGE_PROMPT,
            f"Kontext:\n{context}\n\nFrage: {question}",
        )

    def generate_overview(
        self, topic: str, context: str, system_prompt: str | None = None,
    ) -> str:
        """Generate a structured topic overview (UC#2)."""
        return self._complete(
            system_prompt or OVERVIEW_PROMPT,
            f"Kontext:\n{context}\n\nThema: {topic}",
            max_tokens=3072,
        )

    def generate_overview_stream(
        self, topic: str, context: str, system_prompt: str | None = None,
    ) -> Iterator[str]:
        """Stream a structured topic overview (UC#2)."""
        return self._stream(
            system_prompt or OVERVIEW_PROMPT,
            f"Kontext:\n{context}\n\nThema: {topic}",
            max_tokens=3072,
        )

    def _complete(
        self, system_prompt: str, user_message: str, max_tokens: int = 2048,
    ) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def _stream(
        self, system_prompt: str, user_message: str, max_tokens: int = 2048,
    ) -> Iterator[str]:
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
