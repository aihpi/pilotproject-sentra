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
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from sentra_eval import cases as case_store
from sentra_eval import checks, judge, ragas_checks, variants
from sentra_eval.config import get_eval_settings
from sentra_eval.db import session_scope
from sentra_eval.models import (
    ABGESCHLOSSEN,
    FEHLER,
    FEHLGESCHLAGEN,
    LAUFEND,
    OK,
    ORIGINAL,
    ZWECK_ANTWORT,
    ZWECK_RECALL,
    Call,
    CaseVersion,
    CheckResult,
    GroupCheckResult,
    Run,
)

logger = logging.getLogger(__name__)

# UC#10. The Vorlage is about Fachfragen, so this is the endpoint a round
# exercises. Stored on every call rather than assumed, so a round that used
# something else stays readable.
ANSWER_ENDPOINT = "/api/explorer/answer"

# The recall probe. Made once per case version, not per repeat: it asks what
# the document search can find, which does not vary with the repeat. It has to
# happen during the round because a check that calls SENTRA itself could not be
# re-run over an old round, and because what retrieval returns changes as the
# corpus is re-ingested.
DOCUMENTS_ENDPOINT = "/api/explorer/documents"


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
    zweck: str = ZWECK_ANTWORT

    @property
    def endpoint(self) -> str:
        return DOCUMENTS_ENDPOINT if self.zweck == ZWECK_RECALL else ANSWER_ENDPOINT

    def body(self) -> dict:
        if self.zweck == ZWECK_RECALL:
            # top_k mirrors what the explorer UI asks for, so recall is measured
            # against the list a person would actually be shown.
            return {"query": self.frage, "top_k": 20}
        # debug asks SENTRA for the retrieved chunks, the finish reason and the
        # model it served. Without it there is no truncation check and no way
        # to ask whether a claim was in the context at all.
        return {"query": self.frage, "debug": True}


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
        # 4.2: each approved paraphrase once, not repeated.
        #
        # The Vorlage repeats the *original* prompt three times (4.1) and asks
        # each variant once (4.2). Repeating the variants too would triple the
        # cost of a round — twelve generation calls per case instead of six —
        # for signal 4.1 already provides.
        for variant in variants.approved_for(session, version.id):
            planned.append(
                PlannedCall(
                    case_version_id=version.id,
                    test_id=case.test_id,
                    frage=variant.wortlaut,
                    variant_key=variant.stil,
                    repeat_index=0,
                )
            )

        planned.append(
            PlannedCall(
                case_version_id=version.id,
                test_id=case.test_id,
                frage=version.ausgangsfrage,
                variant_key=ORIGINAL,
                repeat_index=0,
                zweck=ZWECK_RECALL,
            )
        )
    return planned


def outstanding(session: Session, run: Run, retry_failed: bool = True) -> list[PlannedCall]:
    """The planned calls that still need making.

    Resume means "fill in what is missing and try again what failed", because
    the reason to resume is usually that something went wrong. A successful
    call is never repeated: it would spend quota to overwrite evidence.
    """
    done: set[tuple[UUID, str, int, str]] = set()
    for call in session.execute(select(Call).where(Call.run_id == run.id)).scalars():
        if call.status == OK or not retry_failed:
            done.add((call.case_version_id, call.variant_key, call.repeat_index, call.zweck))

    return [
        item
        for item in plan(session, run)
        if (item.case_version_id, item.variant_key, item.repeat_index, item.zweck) not in done
    ]


# ── Executing ───────────────────────────────────────────────────────


def start_run(
    session: Session,
    *,
    label: str = "",
    repeats: int = 3,
    stichprobe_anteil: float = 0.1,
    stichprobe_seed: int | None = None,
    ragas_aktiv: bool = False,
) -> Run:
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
        stichprobe_anteil=stichprobe_anteil,
        ragas_aktiv=ragas_aktiv,
        # Drawn once, at the start, and kept. Stufe 3's job is to detect Stufe 1
        # systematically missing things, which a sample nobody can reconstruct
        # cannot support — so the seed is part of the round's record rather
        # than something regenerated on read.
        stichprobe_seed=stichprobe_seed
        if stichprobe_seed is not None
        else secrets.randbelow(2**31),
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

        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is not None:
                _run_group_checks(session, run)

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
    body = item.body()
    started = time.monotonic()
    status: int | None = None
    response_body: dict = {}
    error = ""

    try:
        response = client.post(item.endpoint, json=body)
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
                Call.zweck == item.zweck,
            )
        ).scalar_one_or_none()

        call = existing or Call(
            run_id=run_id,
            case_version_id=item.case_version_id,
            variant_key=item.variant_key,
            repeat_index=item.repeat_index,
            zweck=item.zweck,
        )
        call.endpoint = item.endpoint
        call.request_body = body
        call.response_body = response_body
        call.http_status = status
        call.dauer_ms = elapsed_ms
        call.fehler = error
        call.status = FEHLER if error else OK
        session.add(call)
        session.flush()
        _run_checks(session, call)


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


# ── Checks ──────────────────────────────────────────────────────────


def _run_checks(session: Session, call: Call) -> None:
    """Score a call as soon as it is stored.

    At run time rather than on read, because what the check said is part of the
    round's record. A check whose rules changed later must not silently rewrite
    what a reported round concluded. Re-running checks over an old round is
    still possible — they are pure functions over these rows — and writes a new
    verdict rather than editing the old one in place.
    """
    if call.status != OK:
        return

    version = session.get(CaseVersion, call.case_version_id)
    if version is None:
        return

    if call.zweck == ZWECK_ANTWORT:
        outcomes = [
            checks.quellenauswahl(call.response_body, version),
            checks.marker_ausrichtung(call.response_body),
            # 4.3a. The retrieved chunks come from the debug payload, which is
            # why the runner asks for it: the check compares the pages the
            # answer names against the pages it actually drew on, and the
            # sources list carries only the best-matching page per document.
            checks.seitenangabe(call.response_body, call.response_body.get("hits") or []),
            checks.ablehnung(
                call.response_body,
                grenzfall=version.grenzfall,
                abgelehnt=_abgelehnt(session, call, version),
            ),
            checks.abschneidung(call.response_body),
        ]
        # ragas only if the round asked for it, and only on the first repeat.
        # Three LLM-scored metrics per answer roughly doubles a round's model
        # calls; scoring every repeat would triple that again for a measure
        # that is about the answer's grounding rather than its consistency.
        run = session.get(Run, call.run_id)
        if run is not None and run.ragas_aktiv and call.repeat_index == 0:
            outcomes.extend(
                ragas_checks.score(
                    call.response_body,
                    frage=version.ausgangsfrage,
                    erwartete_antwort=version.erwartete_antwort,
                )
            )
    else:
        outcomes = [checks.retrieval_recall(call.response_body, version)]

    for outcome in outcomes:
        existing = session.execute(
            select(CheckResult).where(
                CheckResult.call_id == call.id, CheckResult.pruefung == outcome.pruefung
            )
        ).scalar_one_or_none()
        result = existing or CheckResult(call_id=call.id, pruefung=outcome.pruefung)
        result.ergebnis = outcome.ergebnis
        result.auffaellig = outcome.auffaellig
        result.belege = outcome.belege
        session.add(result)


def _abgelehnt(session: Session, call: Call, version: CaseVersion) -> bool | None:
    """Did this answer decline to answer? None means "fall back to the string".

    Two paths, cheap one first. The exact refusal with no sources is
    unambiguous and free, the same shortcut identical repeats give 4.1. It is
    almost never the case, because that string only appears when retrieval
    returns nothing.

    Otherwise the judge decides, because 4.4 accepts prose (#109) and
    recognising "I cannot answer this from the context" is not a string
    comparison.

    Once per *distinct answer*, not once per call. Repeats of a question
    usually come back byte-identical, so this costs one judge call per case in
    the common run while still judging a repeat that came back different —
    which is the repeat worth judging.

    Judging only the first repeat was the bug in #132. The other repeats
    returned None, and None means "compare the literal string", so they did not
    record "not assessed" — they recorded a verdict reached by the rule #109
    decided against. Identical text came out `korrekt abgelehnt` on one row and
    `nicht abgelehnt` on the next, and an ordinary question that SENTRA hedged
    read as clean on two rows out of three.

    A judge that cannot be reached falls back to the literal comparison rather
    than guessing. That reports a hedging Grenzfall as "nicht abgelehnt" —
    which is the old behaviour, conservative, and sends a human to look.
    """
    if checks.ist_wortliche_ablehnung(call.response_body):
        return True

    schon_beurteilt = _judgement_for_the_same_answer(session, call)
    if schon_beurteilt is not None:
        return schon_beurteilt

    try:
        abgelehnt, _grund = judge.beurteile_ablehnung(
            call.response_body.get("text") or "", frage=version.ausgangsfrage
        )
    except judge.JudgeUnavailable as exc:
        logger.warning("Judge could not assess refusal for %s: %s", version.id, exc)
        return None
    return abgelehnt


def _judgement_for_the_same_answer(session: Session, call: Call) -> bool | None:
    """A verdict the judge already gave on this exact text, in this round.

    Through the database rather than a dictionary, because a round resumes:
    `execute` can be re-entered in a new process over calls stored by an
    earlier one, and an in-memory cache would be empty there and would judge
    the same answers again. It also keeps the cache per run, which is what the
    record needs — a verdict belongs to the round that asked for it.

    Scoped to the same case version, since that is the only place identical
    answer text is plausible, and it keeps this to a handful of rows.
    """
    text = (call.response_body.get("text") or "").strip()
    if not text:
        return None

    geschwister = session.execute(
        select(Call).where(
            Call.run_id == call.run_id,
            Call.case_version_id == call.case_version_id,
            Call.zweck == ZWECK_ANTWORT,
            Call.status == OK,
            Call.id != call.id,
        )
    ).scalars()

    for other in geschwister:
        if (other.response_body.get("text") or "").strip() != text:
            continue
        result = session.execute(
            select(CheckResult).where(
                CheckResult.call_id == other.id,
                CheckResult.pruefung == checks.ABLEHNUNG,
            )
        ).scalar_one_or_none()
        if result is None:
            continue
        belege = result.belege or {}
        if belege.get("beurteilt_durch") == checks.DURCH_PRUEFMODELL:
            return bool(belege["abgelehnt"])
    return None


def _run_group_checks(session: Session, run: Run) -> None:
    """Score the checks that are about a group of calls rather than one call.

    Run after the per-call ones, because they need every repeat to exist.
    """
    calls = list(
        session.execute(
            select(Call).where(Call.run_id == run.id, Call.zweck == ZWECK_ANTWORT)
        ).scalars()
    )
    groups: dict[tuple[UUID, str], list[Call]] = {}
    for call in calls:
        if call.status == OK:
            groups.setdefault((call.case_version_id, call.variant_key), []).append(call)

    # 4.2 compares the answer to the original against the answers to its
    # paraphrases — across variants rather than within one, which is what makes
    # it a different check from 4.1 rather than a repeat of it.
    across_variants: dict[UUID, dict[str, str]] = {}
    for call in calls:
        if call.status == OK and call.repeat_index == 0:
            across_variants.setdefault(call.case_version_id, {})[call.variant_key] = (
                call.response_body.get("text") or ""
            )

    for (case_version_id, variant_key), group in groups.items():
        group.sort(key=lambda c: c.repeat_index)
        texts = [c.response_body.get("text") or "" for c in group]
        outcome = checks.wiederholbarkeit(texts)

        existing = session.execute(
            select(GroupCheckResult).where(
                GroupCheckResult.run_id == run.id,
                GroupCheckResult.case_version_id == case_version_id,
                GroupCheckResult.variant_key == variant_key,
                GroupCheckResult.pruefung == outcome.pruefung,
            )
        ).scalar_one_or_none()
        result = existing or GroupCheckResult(
            run_id=run.id,
            case_version_id=case_version_id,
            variant_key=variant_key,
            pruefung=outcome.pruefung,
        )
        result.ergebnis = outcome.ergebnis
        result.auffaellig = outcome.auffaellig
        result.belege = outcome.belege
        session.add(result)

        # 4.1 only needs the judge when the cheap check could not settle it.
        # Identical repeats at temperature 0.1 are common, and every judge call
        # is a real request to a real model — spending one to confirm that two
        # identical strings are identical is waste the Vorlage does not ask
        # for. Differing wording is precisely what it cannot settle.
        if outcome.ergebnis == checks.ABWEICHEND:
            _ask_the_judge(session, run, case_version_id, variant_key, texts)

    for case_version_id, by_variant in across_variants.items():
        if len(by_variant) < 2:
            # No approved paraphrases, so there is no robustness to measure.
            continue
        _ask_the_judge(
            session,
            run,
            case_version_id,
            ORIGINAL,
            [by_variant[k] for k in sorted(by_variant)],
            pruefung=judge.ROBUSTHEIT,
        )


def _ask_the_judge(
    session: Session,
    run: Run,
    case_version_id: UUID,
    variant_key: str,
    texts: list[str],
    pruefung: str = judge.KONSISTENZ,
) -> None:
    """Do these answers differ in substance, or only in wording?

    4.1 over the repeats of one prompt, 4.2 over the answers to a question and
    its paraphrases. Same question to the judge; different sets of answers.

    A judge failure is recorded rather than swallowed. Treating "the judge did
    not answer" as "unauffällig" would mark a case clean because a request
    timed out, which is the quietest way for this process to lie.
    """
    version = session.get(CaseVersion, case_version_id)
    if version is None:
        return

    try:
        verdict = judge.compare(texts, frage=version.ausgangsfrage, pruefung=judge.KONSISTENZ)
        ergebnis = verdict["verdict"]
        auffaellig = ergebnis == judge.AUFFAELLIG
        belege = {
            "dimension": verdict["dimension"],
            "begruendung": verdict["begruendung"],
            "judge_model": verdict["judge_model"],
            "anzahl_antworten": len(texts),
        }
    except judge.JudgeUnavailable as exc:
        logger.warning("Judge unavailable for %s: %s", version.id, exc)
        ergebnis = judge.JUDGE_FEHLER
        # Flagged: a case the judge could not read is a case a human has to.
        auffaellig = True
        belege = {"fehler": str(exc), "anzahl_antworten": len(texts)}

    existing = session.execute(
        select(GroupCheckResult).where(
            GroupCheckResult.run_id == run.id,
            GroupCheckResult.case_version_id == case_version_id,
            GroupCheckResult.variant_key == variant_key,
            GroupCheckResult.pruefung == pruefung,
        )
    ).scalar_one_or_none()
    result = existing or GroupCheckResult(
        run_id=run.id,
        case_version_id=case_version_id,
        variant_key=variant_key,
        pruefung=pruefung,
    )
    result.ergebnis = ergebnis
    result.auffaellig = auffaellig
    result.belege = belege
    session.add(result)


def recheck(session: Session, run: Run) -> int:
    """Re-run every check over a finished round, without calling SENTRA.

    The property the checks were shaped around: they are pure functions over
    stored rows, so a round can be scored again by a check that did not exist
    when it ran.
    """
    scored = 0
    for call in session.execute(select(Call).where(Call.run_id == run.id)).scalars():
        _run_checks(session, call)
        scored += 1
    _run_group_checks(session, run)
    return scored
