"""Turning a complaint into a test case.

Phase 1 of the Vorlage: "Ergänzend werden bekannte Problemfälle aus vorherigen
Rückmeldungen gezielt aufgenommen, da sich dort erfahrungsgemäß Schwachstellen
wiederholen." SENTRA has been recording ratings since #16 and nothing has ever
read them back.

Fetched over HTTP like everything else the harness asks SENTRA for — it is a
separate distribution with its own container and no access to that file.

**Only the question and the reason come across.** Not the answer. The expected
answer is the yardstick a round measures against, and prefilling it from
SENTRA's own output would let the system under test define what counts as
correct — which is the one thing the case store was shaped to prevent.
"""

import logging
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from sentra_eval import cases as case_store
from sentra_eval.categories import Kategorie
from sentra_eval.config import get_eval_settings, sentra_headers
from sentra_eval.models import Case

logger = logging.getLogger(__name__)

FEEDBACK_ENDPOINT = "/api/feedback"


class FeedbackError(RuntimeError):
    """Feedback could not be read, or has already been used."""


class AlreadyImported(FeedbackError):
    """A case was already drafted from this entry."""


@dataclass(frozen=True)
class FeedbackEntry:
    id: str
    timestamp: str
    question: str
    answer: str
    rating: str
    comment: str


def fetch(
    rating: str | None = "negative", client: httpx.Client | None = None
) -> list[FeedbackEntry]:
    """Recorded feedback from SENTRA, newest first.

    Negative by default: a rating somebody bothered to complain about is where
    the Vorlage expects weaknesses to repeat, and it is the shorter list.
    """
    settings = get_eval_settings()
    owned = client is None
    client = client or httpx.Client(
        base_url=settings.sentra_base_url,
        timeout=settings.runner_timeout_seconds,
        headers=sentra_headers(settings),
    )
    try:
        response = client.get(FEEDBACK_ENDPOINT, params={"rating": rating} if rating else None)
        response.raise_for_status()
        raw = response.json()
    except httpx.HTTPError as exc:
        raise FeedbackError(f"Could not read feedback from SENTRA: {exc}") from exc
    finally:
        if owned:
            client.close()

    return [
        FeedbackEntry(
            id=item.get("id", ""),
            timestamp=item.get("timestamp", ""),
            question=item.get("question", ""),
            answer=item.get("answer", ""),
            rating=item.get("rating", ""),
            comment=item.get("comment") or "",
        )
        for item in raw
    ]


def draft_case(session: Session, entry: FeedbackEntry, *, kategorie: Kategorie) -> tuple[Case, str]:
    """Start a case from a complaint. Returns the case and the answer that caused it.

    The answer comes back to the caller so a reviewer can see what went wrong
    while writing the expected answer — and is deliberately not stored on the
    case, because a yardstick taken from the system under test is not a
    yardstick.

    The case is a draft with no expected answer and no reference source, so it
    is not runnable until somebody supplies both. That is the existing rule,
    inherited rather than restated here.
    """
    if not entry.question.strip():
        raise FeedbackError("That feedback entry has no question to build a case from.")

    existing = case_store.from_feedback(session, entry.id)
    if existing is not None:
        raise AlreadyImported(
            f"This feedback was already used for {existing.test_id}. The same complaint twice "
            f"would weight one problem more heavily than the rest of the round."
        )

    case, _version = case_store.create_case(
        session,
        kategorie=kategorie,
        ausgangsfrage=entry.question,
        abteilung="Hotline",
        grund_fuer_aufnahme=(
            f"Aus Rückmeldung vom {entry.timestamp[:10]}"
            + (f": {entry.comment}" if entry.comment else "")
        ),
        feedback_id=entry.id,
    )
    return case, entry.answer
