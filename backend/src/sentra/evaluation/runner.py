"""Running a round against SENTRA.

Over HTTP, at SENTRA_BASE_URL, never in process. The API layer is part of what
is under test: calling services/explorer.py directly would skip the request
models, the routing and the error policy, which is where a regression is most
likely to hide. The runner is a client like any other.

Resumable, because a round costs about 180 generation calls at 20 to 29 seconds
each. Losing one to a restart at call 45 is an hour of wall clock and a slice of
hub quota, so every call is committed as it completes and the call rows are the
progress record. Continuing means working the plan out again and skipping what
is already there.

This task stores calls and nothing else. No checks, no judge: what it produces
is a complete, readable record of what was asked and what came back, which is
what every later check is a pure function over.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from sentra.evaluation import cases as case_store
from sentra.evaluation.config import get_eval_settings
from sentra.evaluation.db import session_scope
from sentra.evaluation.models import (
    ABGESCHLOSSEN,
    FEHLER,
    FEHLGESCHLAGEN,
    LAUFEND,
    OK,
    ORIGINAL,
    Call,
    CaseVersion,
    Run,
)

logger = logging.getLogger(__name__)

# UC#10. The Vorlage is about Fachfragen, so this is the endpoint a round
# exercises. Stored on every call rather than assumed, so a round that used
# something else stays readable.
ANSWER_ENDPOINT = "/api/explorer/answer"


class RunnerError(RuntimeError):
    """A round could not be started."""


@dataclass(frozen=True)
class PlannedCall:
    """One call a round intends to make."""

    case_version_id: UUID
    test_id: str
    frage: str
    variant_key: str
    repeat_index: int


# ── Planning ────────────────────────────────────────────────────────


def plan(session: Session, run: Run) -> list[PlannedCall]:
    """Every call the round should consist of.

    Built from the approved version of each case, not the newest one, so that
    somebody drafting the next round's wording cannot change what this round is
    measuring.
    """
    planned: list[PlannedCall] = []
    for case in case_store.list_cases(session):
        version = case_store.latest_approved(case)
        if version is None:
            logger.info("%s has no approved version, skipping", case.test_id)
            continue
        for repeat_index in range(run.repeats):
            planned.append(
                PlannedCall(
                    case_version_id=version.id,
                    test_id=case.test_id,
                    frage=version.ausgangsfrage,
                    variant_key=ORIGINAL,
                    repeat_index=repeat_index,
                )
            )
    return planned


def outstanding(session: Session, run: Run, retry_failed: bool = True) -> list[PlannedCall]:
    """The planned calls that still need making.

    Resume means "fill in what is missing and try again what failed", because
    the reason to resume is usually that something went wrong. A successful
    call is never repeated: it would spend quota to overwrite evidence.
    """
    done: set[tuple[UUID, str, int]] = set()
    for call in session.execute(select(Call).where(Call.run_id == run.id)).scalars():
        if call.status == OK or not retry_failed:
            done.add((call.case_version_id, call.variant_key, call.repeat_index))

    return [
        item
        for item in plan(session, run)
        if (item.case_version_id, item.variant_key, item.repeat_index) not in done
    ]


# ── Executing ───────────────────────────────────────────────────────


def start_run(session: Session, *, label: str = "", repeats: int = 3) -> Run:
    """Create a round. Refuses one with nothing to do.

    A round over zero approved cases would sit at "completed, 0 calls" and look
    like a harness that silently does nothing, which is worse than an error.
    """
    settings = get_eval_settings()
    run = Run(
        label=label,
        status=LAUFEND,
        sentra_base_url=settings.sentra_base_url,
        repeats=repeats,
    )
    session.add(run)
    session.flush()

    if not plan(session, run):
        raise RunnerError(
            "No approved case versions, so there is nothing to run. Approve at least one "
            "case first — a draft is not a yardstick."
        )
    return run


def execute(run_id: UUID, client: httpx.Client | None = None) -> None:
    """Work through a round, committing each call as it completes.

    One session per call, deliberately. A single transaction around the whole
    round would mean a crash at call 45 discards all 45, which is the thing
    resumability exists to prevent.
    """
    settings = get_eval_settings()
    owned_client = client is None
    client = client or httpx.Client(
        base_url=settings.sentra_base_url, timeout=settings.runner_timeout_seconds
    )

    try:
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is None:
                raise RunnerError(f"No run {run_id}")
            todo = outstanding(session, run)
            logger.info("Run %s: %d calls to make", run_id, len(todo))

        for item in todo:
            _make_one_call(run_id, item, client)

        _finish(run_id)
    except Exception as exc:  # noqa: BLE001 — recorded on the run, not swallowed
        logger.exception("Run %s failed", run_id)
        _finish(run_id, error=str(exc))
    finally:
        if owned_client:
            client.close()


def _make_one_call(run_id: UUID, item: PlannedCall, client: httpx.Client) -> None:
    """One request, stored whichever way it goes.

    A failure is a row, not a lost round. An unreachable SENTRA halfway through
    is a fact about that call, and the remaining cases still have to be tried —
    otherwise one blip costs the whole round.
    """
    body = {"query": item.frage}
    started = time.monotonic()
    status: int | None = None
    response_body: dict = {}
    error = ""

    try:
        response = client.post(ANSWER_ENDPOINT, json=body)
        status = response.status_code
        try:
            response_body = response.json()
        except ValueError:
            response_body = {"raw": response.text[:4000]}
        if response.is_error:
            error = f"HTTP {status}"
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"

    elapsed_ms = (time.monotonic() - started) * 1000

    with session_scope() as session:
        existing = session.execute(
            select(Call).where(
                Call.run_id == run_id,
                Call.case_version_id == item.case_version_id,
                Call.variant_key == item.variant_key,
                Call.repeat_index == item.repeat_index,
            )
        ).scalar_one_or_none()

        call = existing or Call(
            run_id=run_id,
            case_version_id=item.case_version_id,
            variant_key=item.variant_key,
            repeat_index=item.repeat_index,
        )
        call.endpoint = ANSWER_ENDPOINT
        call.request_body = body
        call.response_body = response_body
        call.http_status = status
        call.dauer_ms = elapsed_ms
        call.fehler = error
        call.status = FEHLER if error else OK
        session.add(call)


def _finish(run_id: UUID, error: str = "") -> None:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        remaining = outstanding(session, run)
        run.completed_at = datetime.now(UTC)
        if error:
            run.status = FEHLGESCHLAGEN
            run.fehler = error
        elif remaining:
            # Every call was attempted and some are still not OK. The round is
            # finished but not clean, and saying "abgeschlossen" would hide that.
            run.status = FEHLGESCHLAGEN
            run.fehler = f"{len(remaining)} calls did not succeed"
        else:
            run.status = ABGESCHLOSSEN


# ── Reading ─────────────────────────────────────────────────────────


@dataclass
class RunProgress:
    run: Run
    total: int
    done: int
    failed: int


def progress(session: Session, run: Run) -> RunProgress:
    calls = list(session.execute(select(Call).where(Call.run_id == run.id)).scalars())
    return RunProgress(
        run=run,
        total=len(plan(session, run)),
        done=sum(1 for c in calls if c.status == OK),
        failed=sum(1 for c in calls if c.status == FEHLER),
    )


def get_run(session: Session, run_id: UUID) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise RunnerError(f"No run {run_id}")
    return run


def audit_is_sound(session: Session, run: Run) -> bool:
    """Whether every version this round used was approved before it started.

    The property the case store was shaped around, checkable after the fact.
    A round where this is false has measured answers against an expectation
    that could have been written to fit them.
    """
    for call in session.execute(select(Call).where(Call.run_id == run.id)).scalars():
        version = session.get(CaseVersion, call.case_version_id)
        if version is None or version.freigegeben_at is None:
            return False
        if version.freigegeben_at > run.started_at:
            return False
    return True
