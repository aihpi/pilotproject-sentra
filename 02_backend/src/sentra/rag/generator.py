import logging

from openai import OpenAI

from sentra.config import Settings
from sentra.domain import Hit

logger = logging.getLogger(__name__)

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


# The prompt each question sub-mode starts from, served by GET /api/config so
# the UI can show and reset the default without keeping its own copy. The keys
# are the sub-mode ids the frontend uses and are therefore part of the API
# contract: renaming one here renames it in the UI.
#
# The document sub-modes (thema, aehnliche, quellen) do not generate text and
# so have no entry.
DEFAULT_PROMPTS: dict[str, str] = {
    "fachfrage": FACHFRAGE_PROMPT,
    "ueberblick": OVERVIEW_PROMPT,
}


def format_context(hits: list[Hit]) -> str:
    """Format retrieved chunks into the context string the model sees.

    This is the whole universe the model gets per hit: an Aktenzeichen, a section
    title and the chunk text. There is no page or paragraph, which is why a
    generated citation cannot be more precise than a section.
    """
    parts = []
    for hit in hits:
        header = f"[Quelle: {hit.aktenzeichen}, Abschnitt: {hit.section_title}]"
        parts.append(f"{header}\n{hit.text}")
    return "\n\n---\n\n".join(parts)


class AnswerGenerator:
    """Generate answers from retrieved context using an LLM."""

    def __init__(self, settings: Settings) -> None:
        self._client = OpenAI(
            base_url=settings.ai_hub_base_url,
            api_key=settings.ai_hub_api_key,
        )
        self._model = settings.chat_model

    def generate_answer(
        self,
        question: str,
        context: str,
        system_prompt: str | None = None,
    ) -> str:
        """Generate a focused answer for a Fachfrage (UC#10)."""
        return self._complete(
            system_prompt or FACHFRAGE_PROMPT,
            f"Kontext:\n{context}\n\nFrage: {question}",
        )

    def generate_overview(
        self,
        topic: str,
        context: str,
        system_prompt: str | None = None,
    ) -> str:
        """Generate a structured topic overview (UC#2)."""
        return self._complete(
            system_prompt or OVERVIEW_PROMPT,
            f"Kontext:\n{context}\n\nThema: {topic}",
            max_tokens=3072,
        )

    def _complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2048,
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
