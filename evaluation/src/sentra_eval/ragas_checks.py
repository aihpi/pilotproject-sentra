"""ragas scores, mapped to verdicts, behind the same interface as everything else.

An addition rather than a replacement. ragas covers roughly one of the six
deterministic checks and cannot do 4.1, 4.2, 4.3a, 4.3b or any of the process.
What it adds is answer correctness against the expected answer, and context
precision and recall over what retrieval returned.

**The caveat that matters, and it belongs next to the code rather than in a
document nobody opens.** Faithfulness asks whether a claim is grounded in *any*
retrieved context. 4.3c asks whether it is supported by *the cited* source. A
claim taken from chunk 5 and cited as `[2]` passes faithfulness and fails 4.3c.
The metric is useful and it is not the check, so it is reported under its own
name and never as 4.3c.

Optional. ragas is 97 packages against this harness's twelve, so it is an extra
and this module imports it lazily: without it the checks report "nicht prüfbar"
rather than failing a round.

No reviewer ever sees a score. A number between zero and one is something a
person has to learn to interpret, and two people will interpret it differently
— which is the opposite of what a queue of verdicts is for. The threshold does
the interpreting, once, and is recorded on the run so that changing it later
cannot change what a finished round concluded.
"""

import logging
from typing import Any

from sentra_eval.checks import NICHT_PRUEFBAR, CheckOutcome

logger = logging.getLogger(__name__)

# Check names, stable keys in the database and the trend report.
RAGAS_TREUE = "ragas_treue"  # faithfulness
RAGAS_ANTWORTGUETE = "ragas_antwortguete"  # answer correctness
RAGAS_KONTEXT = "ragas_kontext"  # context precision

# German, like every other verdict a reviewer reads.
AUSREICHEND = "ausreichend"
UNZUREICHEND = "unzureichend"

# Default thresholds. Guesses, and labelled as such: nobody has calibrated
# these against human verdicts, which is the only thing that could. They are
# recorded on the run so a round's conclusions do not move when they change.
DEFAULT_SCHWELLEN = {
    RAGAS_TREUE: 0.7,
    RAGAS_ANTWORTGUETE: 0.6,
    RAGAS_KONTEXT: 0.5,
}


class RagasUnavailable(RuntimeError):
    """ragas is not installed, or could not score this call."""


def is_available() -> bool:
    """Whether the extra is installed. Cheap, and does not import the world."""
    from importlib.util import find_spec

    return find_spec("ragas") is not None


def contexts_from(response: dict) -> list[str]:
    """The retrieved chunks, from the debug payload.

    Without them ragas has nothing to score against: faithfulness and context
    precision are both about the retrieved context, and answer correctness
    alone would not be worth the dependency.
    """
    return [hit.get("text", "") for hit in (response.get("hits") or []) if hit.get("text")]


def score(
    response: dict,
    *,
    frage: str,
    erwartete_antwort: str,
    schwellen: dict[str, float] | None = None,
) -> list[CheckOutcome]:
    """Score one stored call. Returns one outcome per metric.

    Pure over the stored row like every other check, so a finished round can be
    scored later — the only difference is that this one needs a model, so it is
    not free to re-run.
    """
    schwellen = {**DEFAULT_SCHWELLEN, **(schwellen or {})}

    if not is_available():
        return _all_unavailable(schwellen, "ragas ist nicht installiert (uv sync --extra ragas).")

    contexts = contexts_from(response)
    if not contexts:
        return _all_unavailable(
            schwellen,
            "Die Antwort wurde ohne debug-Flag abgerufen, es gibt keinen Kontext zum Prüfen.",
        )

    try:
        scores: dict[str, float | None] = _run_ragas(
            frage=frage,
            antwort=response.get("text") or "",
            contexts=contexts,
            erwartete_antwort=erwartete_antwort,
        )
    except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
        logger.warning("ragas could not score this call: %s", exc)
        return _all_unavailable(schwellen, f"ragas-Fehler: {exc}")

    return [
        _verdict(name, scores.get(name), schwellen[name])
        for name in (RAGAS_TREUE, RAGAS_ANTWORTGUETE, RAGAS_KONTEXT)
    ]


def _run_ragas(
    *, frage: str, antwort: str, contexts: list[str], erwartete_antwort: str
) -> dict[str, float | None]:
    """The actual call. Imported here so the module loads without the extra.

    Uses the judge model rather than CHAT_MODEL: a metric computed by the
    system under test is not a measurement of it.
    """
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import SingleTurnSample, evaluate
    from ragas.dataset_schema import EvaluationDataset
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import AnswerCorrectness, Faithfulness, LLMContextPrecisionWithReference

    from sentra_eval.config import get_eval_settings
    from sentra_eval.judge import judge_config

    config = judge_config()
    llm = LangchainLLMWrapper(
        ChatOpenAI(model=config.model, base_url=config.base_url, api_key=config.api_key)
    )

    sample = SingleTurnSample(
        user_input=frage,
        response=antwort,
        retrieved_contexts=contexts,
        reference=erwartete_antwort,
    )
    result = evaluate(
        dataset=EvaluationDataset(samples=[sample]),
        metrics=[Faithfulness(), AnswerCorrectness(), LLMContextPrecisionWithReference()],
        llm=llm,
        # The hub's embedding model, not OpenAI's default. ragas asks for
        # text-embedding-ada-002 unless told otherwise, which this hub does not
        # serve — and the failure surfaces as a NaN score rather than an error,
        # which is how it went unnoticed until _as_float started rejecting NaN.
        # base_url and api_key are pydantic aliases langchain accepts at
        # runtime; the declared fields are openai_api_base and openai_api_key,
        # which is why mypy objects. Verified against the live hub rather than
        # swapped for the declared names untested.
        embeddings=OpenAIEmbeddings(  # type: ignore[call-arg]
            model=get_eval_settings().ragas_embedding_model,
            base_url=config.base_url,
            api_key=config.api_key,
            check_embedding_ctx_length=False,
        ),
        show_progress=False,
    )
    raw: dict[str, Any] = result.scores[0] if result.scores else {}
    return {
        RAGAS_TREUE: _as_float(raw.get("faithfulness")),
        RAGAS_ANTWORTGUETE: _as_float(raw.get("answer_correctness")),
        RAGAS_KONTEXT: _as_float(raw.get("llm_context_precision_with_reference")),
    }


def _as_float(value: Any) -> float | None:
    """A score, or None when there is not one.

    NaN counts as "not one", and that is not pedantry. ragas returns NaN for a
    metric it could not compute — a missing embedding model, say — and NaN
    fails every comparison, so `nan < schwelle` is False and a NaN score fell
    straight through to "ausreichend". A metric that failed to run was being
    reported as a passing verdict, which marks a case clean for a reason that
    has nothing to do with the answer. Found against the live hub, where answer
    correctness returned NaN because the embedding model was wrong.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _verdict(name: str, value: float | None, schwelle: float) -> CheckOutcome:
    """Score plus threshold to a verdict. The score stays in the evidence.

    A reviewer reads "unzureichend", not "0.62". The number is kept because the
    trend report can use it and because a verdict whose basis nobody can see is
    an assertion — but it is evidence, not the answer.
    """
    # None or NaN. The guard is here, at the decision, rather than only where
    # the value is parsed — a threshold comparison is the last place a bad
    # value can still become a verdict, and NaN fails every comparison, so
    # `nan < schwelle` is False and it would fall through to "ausreichend".
    # A metric that never ran would be reported as a passing one.
    if value is None or value != value:
        return CheckOutcome(
            name, NICHT_PRUEFBAR, auffaellig=False, belege={"grund": "Kein Wert berechnet."}
        )
    belege = {"wert": round(value, 4), "schwelle": schwelle}
    if value < schwelle:
        return CheckOutcome(name, UNZUREICHEND, auffaellig=True, belege=belege)
    return CheckOutcome(name, AUSREICHEND, auffaellig=False, belege=belege)


def _all_unavailable(schwellen: dict[str, float], grund: str) -> list[CheckOutcome]:
    return [
        CheckOutcome(name, NICHT_PRUEFBAR, auffaellig=False, belege={"grund": grund})
        for name in (RAGAS_TREUE, RAGAS_ANTWORTGUETE, RAGAS_KONTEXT)
    ]
