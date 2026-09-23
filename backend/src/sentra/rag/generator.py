import logging
from typing import Protocol

from openai import OpenAI

from sentra.config import Settings
from sentra.domain import Generation, Hit

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


class AnswerMethod(Protocol):
    """One of AnswerGenerator's generating methods, already bound.

    generate_answer and generate_overview have the same shape, which is what
    let the explorer service pick between them by name and hand the string to
    getattr. This states the shape instead, so passing the wrong thing is a
    type error and renaming a method updates its callers.

    The first two parameters are positional-only here because the real methods
    disagree on what to call the first one: a question for one, a topic for
    the other.
    """

    def __call__(
        self, question: str, context: str, /, *, system_prompt: str | None = None
    ) -> Generation: ...


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

    This is the whole universe the model gets per hit, so a citation can be no
    more precise than this header. It carried an Aktenzeichen and a section
    title, which is why a generated citation could not be finer than a section
    — and a section can run for four pages, which is not something a reviewer
    can check by hand. Since #134 it carries the page and paragraph as well.

    The location is omitted rather than faked where the chunk has none. Every
    point written before #134 has no page recorded, and inventing one would
    produce a citation that looks checkable and is not — which is worse than a
    section reference that is honest about its precision.
    """
    parts = []
    for hit in hits:
        header = f"[Quelle: {hit.aktenzeichen}, Abschnitt: {hit.section_title}"
        location = format_location(hit)
        if location:
            header += f", {location}"
        parts.append(f"{header}]\n{hit.text}")
    return "\n\n---\n\n".join(parts)


def format_location(hit: Hit) -> str:
    """ "Seite 4, Absatz 3" or "Seite 4, Absatz 3 bis Seite 5, Absatz 1".

    Empty where the chunk carries no page — see format_context.

    German, because it goes into a German prompt and comes back in a German
    answer; a model told "page" tends to write "page". The paragraph is given
    with its page on both ends because the count restarts on each page, so
    "Absatz 3" means nothing without knowing which page it is on.
    """
    if not hit.page_from:
        return ""

    start = f"Seite {hit.page_from}"
    if hit.paragraph_from:
        start += f", Absatz {hit.paragraph_from}"

    if (hit.page_to, hit.paragraph_to) == (hit.page_from, hit.paragraph_from):
        return start

    end = f"Seite {hit.page_to}"
    if hit.paragraph_to:
        end += f", Absatz {hit.paragraph_to}"
    return f"{start} bis {end}"


class AnswerGenerator:
    """Generate answers from retrieved context using an LLM."""

    def __init__(self, settings: Settings) -> None:
        self._client = OpenAI(
            base_url=settings.ai_hub_base_url,
            api_key=settings.ai_hub_api_key,
            timeout=settings.generation_timeout_seconds,
        )
        self._model = settings.chat_model

    def generate_answer(
        self,
        question: str,
        context: str,
        system_prompt: str | None = None,
    ) -> Generation:
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
    ) -> Generation:
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
    ) -> Generation:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        choice = response.choices[0]
        # finish_reason and the served model name were both discarded here.
        # "length" means the answer stopped at the ceiling rather than ending,
        # which is a different finding from an inconsistent answer; and
        # response.model is what the hub actually ran, which is not necessarily
        # the name we asked for.
        return Generation(
            text=choice.message.content or "",
            finish_reason=choice.finish_reason,
            model=response.model,
        )
