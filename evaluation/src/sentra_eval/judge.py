"""The judge model, and the one thing that has to be true of it at boot."""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from openai import OpenAI, OpenAIError

from sentra_eval.config import get_eval_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JudgeConfig:
    """A judge that is actually configured.

    Exists so that everything downstream gets plain strings instead of
    `str | None`. The settings carry the optionality; this is what you get once
    it has been checked, and it is checked once, at boot.
    """

    base_url: str
    api_key: str
    model: str


class MissingJudgeConfiguration(RuntimeError):
    """The harness is switched on with no judge behind it."""


def judge_config() -> JudgeConfig:
    """The judge, or a failure naming exactly what is missing.

    Reading three required settings would give a pydantic error listing three
    missing fields, which is accurate and says nothing about why they are
    wanted. This says it.
    """
    settings = get_eval_settings()
    missing = [
        name
        for name, value in (
            ("JUDGE_BASE_URL", settings.judge_base_url),
            ("JUDGE_API_KEY", settings.judge_api_key),
            ("JUDGE_MODEL", settings.judge_model),
        )
        if not value
    ]
    if missing:
        raise MissingJudgeConfiguration(
            f"The harness is running but {', '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} not set. It needs a judge model "
            f"that is not CHAT_MODEL; see backend/.env.example."
        )
    # Narrowed by the check above, which mypy cannot see through.
    assert settings.judge_base_url and settings.judge_api_key and settings.judge_model
    return JudgeConfig(
        base_url=settings.judge_base_url,
        api_key=settings.judge_api_key,
        model=settings.judge_model,
    )


# ── The comparisons a script cannot make ────────────────────────────

# 4.1 and 4.2 are the only checks that compare answers to each other rather
# than to a fixed expectation, which is why they need a model at all.
KONSISTENZ = "konsistenz"  # 4.1, repeats of the same prompt
ROBUSTHEIT = "robustheit"  # 4.2, paraphrases of the same question

UNAUFFAELLIG = "unauffällig"
AUFFAELLIG = "auffällig"
JUDGE_FEHLER = "Prüfmodell nicht auswertbar"

# Written from the Vorlage's own wording rather than from anything in SENTRA's
# generator. Section 4.1 asks the checking model whether "Kernaussage, genannte
# Zahlen oder zitierte Quellen" differ, "nicht nur der Wortlaut", and warns that
# a judge sharing a model or prompt structure with the system under test merely
# relocates a consistency problem.
JUDGE_SYSTEM_PROMPT = """\
Du prüfst die Konsistenz von Antworten eines anderen KI-Systems.

Dir werden mehrere Antworten auf dieselbe Frage vorgelegt.
Beurteile ausschließlich, ob sich Kernaussage, genannte Zahlen oder zitierte Quellen \
unterscheiden.
Unterschiede in Formulierung, Stil, Länge oder Reihenfolge sind KEINE Abweichung.

Antworte ausschließlich mit JSON in genau dieser Form:
{"verdict": "unauffällig" | "auffällig", \
"dimension": "Kernaussage" | "Zahlen" | "Quellen" | null, \
"begruendung": "ein Satz"}\
"""

# Generous, and not a guess. gpt-oss-120b spends completion tokens on reasoning
# before emitting any content: at 20 tokens it returned finish_reason "length"
# with an entirely empty message, which would have read as a judge that
# declined to answer. Any reasoning model configured here has the same
# appetite, so the budget assumes one.
JUDGE_MAX_TOKENS = 2000


class JudgeUnavailable(RuntimeError):
    """The judge could not be reached, or said nothing usable."""


def compare(answers: list[str], *, frage: str, pruefung: str) -> dict[str, Any]:
    """Ask the judge whether these answers differ in substance.

    Returns the structured verdict, or raises. Structured because the trend
    report aggregates these across rounds and prose cannot be grouped —
    "wo häufen sich Fußnotenfehler" is a group-by or it is somebody reading
    every sheet again.
    """
    if len(answers) < 2:
        raise JudgeUnavailable("Fewer than two answers to compare.")

    config = judge_config()
    client = OpenAI(base_url=config.base_url, api_key=config.api_key, timeout=180)

    body = "\n\n".join(
        [f"Frage: {frage}", *(f"Antwort {i}: {a}" for i, a in enumerate(answers, start=1))]
    )

    try:
        response = client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": body},
            ],
            temperature=0,
            max_tokens=JUDGE_MAX_TOKENS,
        )
    except OpenAIError as exc:
        raise JudgeUnavailable(f"{type(exc).__name__}: {exc}") from exc

    choice = response.choices[0]
    content = (choice.message.content or "").strip()
    if not content:
        # A reasoning model that used its whole budget thinking. Distinguished
        # from a refusal on purpose: reporting "no verdict" as a verdict would
        # quietly mark a case unauffällig.
        raise JudgeUnavailable(
            f"The judge returned no content (finish_reason={choice.finish_reason!r}). "
            f"A reasoning model may need more than {JUDGE_MAX_TOKENS} tokens."
        )

    return parse_verdict(content, pruefung=pruefung, model=response.model)


def parse_verdict(content: str, *, pruefung: str, model: str | None = None) -> dict[str, Any]:
    """Read the judge's JSON, tolerantly but without inventing a verdict.

    Models wrap JSON in prose or code fences however firmly they are asked not
    to, so the object is extracted rather than the whole string parsed. What is
    not tolerated is a missing or unrecognised verdict: guessing one would put
    a case through Stufe 1 on the strength of a parsing accident.
    """
    match = re.search(r"\{.*\}", content, re.S)
    if match is None:
        raise JudgeUnavailable(f"No JSON object in the judge's reply: {content[:200]!r}")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise JudgeUnavailable(f"The judge's JSON did not parse: {exc}") from exc

    verdict = parsed.get("verdict")
    if verdict not in (UNAUFFAELLIG, AUFFAELLIG):
        raise JudgeUnavailable(f"Unrecognised verdict {verdict!r} from the judge.")

    return {
        "pruefung": pruefung,
        "verdict": verdict,
        "dimension": parsed.get("dimension"),
        "begruendung": str(parsed.get("begruendung") or "")[:1000],
        "judge_model": model,
    }


# ── 4.4: did it say it could not answer? ────────────────────────────

ABLEHNUNG_SYSTEM_PROMPT = """\
Du beurteilst, ob ein Auskunftssystem eine Frage beantwortet oder abgelehnt hat.

Eine Ablehnung liegt vor, wenn die Antwort erkennbar sagt, dass sie die Frage auf Basis der \
vorliegenden Unterlagen nicht beantworten kann — unabhängig davon, wie sie das formuliert.

Keine Ablehnung liegt vor, wenn die Antwort die Frage inhaltlich beantwortet, auch wenn sie \
dabei Einschränkungen nennt.

Antworte ausschließlich mit JSON:
{"abgelehnt": true | false, "begruendung": "ein Satz"}\
"""


def beurteile_ablehnung(text: str, *, frage: str) -> tuple[bool, str]:
    """Whether an answer declined to answer. Returns the verdict and its reason.

    4.4 accepts prose (#109): SENTRA signals that it cannot answer by saying so
    in its own words rather than by taking the no-results path, because that
    path needs retrieval to return nothing and vector search always returns
    something. Recognising that is not a string comparison.

    Raises rather than guessing. A judge that cannot be read must not be
    recorded as "it answered normally" — for a Grenzfall that is the verdict
    that says nothing was wrong, which is the one place this check must not be
    wrong quietly.
    """
    config = judge_config()
    client = OpenAI(base_url=config.base_url, api_key=config.api_key, timeout=180)

    try:
        response = client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": ABLEHNUNG_SYSTEM_PROMPT},
                {"role": "user", "content": f"Frage: {frage}\n\nAntwort: {text}"},
            ],
            temperature=0,
            max_tokens=JUDGE_MAX_TOKENS,
        )
    except OpenAIError as exc:
        raise JudgeUnavailable(f"{type(exc).__name__}: {exc}") from exc

    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise JudgeUnavailable(
            f"The judge returned no content (finish_reason={response.choices[0].finish_reason!r})."
        )

    match = re.search(r"\{.*\}", content, re.S)
    if match is None:
        raise JudgeUnavailable(f"No JSON object in the judge's reply: {content[:200]!r}")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise JudgeUnavailable(f"The judge's JSON did not parse: {exc}") from exc

    abgelehnt = parsed.get("abgelehnt")
    if not isinstance(abgelehnt, bool):
        raise JudgeUnavailable(f"Unrecognised value for abgelehnt: {abgelehnt!r}")

    return abgelehnt, str(parsed.get("begruendung") or "")[:1000]
