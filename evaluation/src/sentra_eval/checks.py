"""Deterministic checks. No model, no judgement, no threshold.

Every check here is a pure function over rows that are already stored, which is
what lets a finished round be re-checked later — including with checks that did
not exist when it ran. A check that has to call SENTRA could not do that, which
is why the recall probe is made during the round and read here.

The vocabulary is the Vorlage's. 4.3b asks whether SENTRA cited the source
recorded as correct or reached for the plausible-but-outdated one, and it
answers `korrekte Quelle` or `falsche bzw. veraltete Quelle`. Not a score: a
reviewer working through a queue needs a verdict they can act on, and "0.72"
is a number they would have to learn to interpret.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from sentra_eval.models import CaseVersion

# Check names, used as stable keys in the database and the trend report.
QUELLENAUSWAHL = "quellenauswahl"  # 4.3b
RETRIEVAL_RECALL = "retrieval_recall"  # new, not in the Vorlage

# Verdicts. The first two are the Vorlage's wording for 4.3b.
KORREKTE_QUELLE = "korrekte Quelle"
FALSCHE_QUELLE = "falsche bzw. veraltete Quelle"
NICHT_PRUEFBAR = "nicht prüfbar"
GEFUNDEN = "gefunden"
NICHT_GEFUNDEN = "nicht gefunden"


@dataclass
class CheckOutcome:
    """One verdict, and what it was based on."""

    pruefung: str
    ergebnis: str
    auffaellig: bool
    belege: dict[str, Any] = field(default_factory=dict)


def normalise_aktenzeichen(value: str) -> str:
    """Compare Aktenzeichen by content, not by spacing.

    The same document is written "WD 3 - 3000 - 029/23" in one place and
    "WD 3-3000-029/23" in another depending on who typed it, and a check that
    calls those different would report a wrong source on a right answer — the
    most expensive kind of false finding, because it sends a reviewer to read a
    document that was cited correctly.
    """
    return re.sub(r"[\s\-]+", "", value).upper()


def _cited(response: dict) -> list[str]:
    sources = response.get("sources") or []
    return [s.get("aktenzeichen", "") for s in sources if isinstance(s, dict)]


# ── 4.3b: did it cite the right one of two plausible sources? ───────


def quellenauswahl(response: dict, version: CaseVersion) -> CheckOutcome:
    """Whether the answer cited the correct reference, or the outdated one.

    A case with no correct Aktenzeichen recorded is "nicht prüfbar" rather than
    a failure. That is a real state — a legal question SENTRA holds no document
    for — and reporting it as failed would fill the first round with findings
    about the case file rather than about SENTRA.
    """
    expected = version.referenz_korrekt_az.strip()
    if not expected:
        return CheckOutcome(
            QUELLENAUSWAHL,
            NICHT_PRUEFBAR,
            auffaellig=False,
            belege={"grund": "Für diesen Testfall ist kein Aktenzeichen hinterlegt."},
        )

    cited = _cited(response)
    cited_keys = {normalise_aktenzeichen(az) for az in cited}
    korrekt_zitiert = normalise_aktenzeichen(expected) in cited_keys

    wrong = version.referenz_falsch_az.strip()
    falsch_zitiert = bool(wrong) and normalise_aktenzeichen(wrong) in cited_keys

    belege = {
        "zitierte_quellen": cited,
        "referenz_korrekt": expected,
        "referenz_korrekt_zitiert": korrekt_zitiert,
        "referenz_falsch": wrong,
        "referenz_falsch_zitiert": falsch_zitiert,
    }

    # Citing the outdated source is the finding the two reference fields exist
    # to catch, and it outranks the correct one also being present: an answer
    # drawing on both still drew on the wrong one.
    if falsch_zitiert:
        return CheckOutcome(QUELLENAUSWAHL, FALSCHE_QUELLE, auffaellig=True, belege=belege)
    if korrekt_zitiert:
        return CheckOutcome(QUELLENAUSWAHL, KORREKTE_QUELLE, auffaellig=False, belege=belege)
    return CheckOutcome(QUELLENAUSWAHL, FALSCHE_QUELLE, auffaellig=True, belege=belege)


# ── Retrieval recall: was it even findable? ─────────────────────────


def retrieval_recall(recall_response: dict, version: CaseVersion) -> CheckOutcome:
    """At what rank the expected document appears in the document search.

    This is what separates "the answer did not cite it" from "retrieval never
    offered it". `/explorer/answer` searches at raw top_k (10) while
    `/explorer/documents` searches top_k * 3 and aggregates, so a source missing
    from an answer is usually a chunk at rank 11 rather than a retrieval
    failure — and sending somebody after the retriever for a ranking problem
    wastes the most expensive thing in this process, which is reviewer time.
    """
    expected = version.referenz_korrekt_az.strip()
    if not expected:
        return CheckOutcome(
            RETRIEVAL_RECALL,
            NICHT_PRUEFBAR,
            auffaellig=False,
            belege={"grund": "Für diesen Testfall ist kein Aktenzeichen hinterlegt."},
        )

    documents = recall_response.get("documents") or []
    wanted = normalise_aktenzeichen(expected)
    rank: int | None = None
    for index, document in enumerate(documents, start=1):
        if normalise_aktenzeichen(document.get("aktenzeichen", "")) == wanted:
            rank = index
            break

    belege = {
        "referenz_korrekt": expected,
        "rang": rank,
        "gefundene_dokumente": len(documents),
    }
    if rank is None:
        return CheckOutcome(RETRIEVAL_RECALL, NICHT_GEFUNDEN, auffaellig=True, belege=belege)
    return CheckOutcome(RETRIEVAL_RECALL, GEFUNDEN, auffaellig=False, belege=belege)


# ── Marker alignment: 4.3a, as far as the data allows ───────────────

MARKER_AUSRICHTUNG = "marker_ausrichtung"
AUSGERICHTET = "Marker und Quellen stimmen überein"
NICHT_AUSGERICHTET = "Marker und Quellen weichen ab"

# "[1]", "[12]". Markdown bold around it ("**[1]**") is what the prompts ask
# for, and the brackets are what the model actually emits either way.
MARKER_PATTERN = re.compile(r"\[(\d{1,2})\]")


def marker_ausrichtung(response: dict) -> CheckOutcome:
    """Whether every [n] has an nth source, and every source is cited.

    Both prompts state that a source number refers to the nth source in order
    of first appearance. Nothing enforces it: the model counts for itself, and
    _build_source_refs numbers independently. A [4] against three sources is
    the visible half; a source nobody cited is the quieter half, and it means
    the answer drew on less than it was given.

    This is 4.3a as far as the data allows and no further. format_context gives
    the model an Aktenzeichen, a section title and the chunk text — no page, no
    paragraph, no offset — so whether a quotation appears at the cited place is
    answerable at section granularity only. That is a data problem, not a
    prompt problem, and it stays open.
    """
    text = response.get("text") or ""
    sources = response.get("sources") or []

    used = sorted({int(m) for m in MARKER_PATTERN.findall(text)})
    available = list(range(1, len(sources) + 1))

    dangling = [n for n in used if n not in available]
    uncited = [n for n in available if n not in used]

    belege = {
        "verwendete_marker": used,
        "anzahl_quellen": len(sources),
        # A marker pointing at a source that is not there. The model invented a
        # number, and a reviewer following it finds nothing.
        "marker_ohne_quelle": dangling,
        # A source the answer never referred to. Evidence, not a finding — see
        # below.
        "quellen_ohne_marker": uncited,
    }

    # Only a dangling marker is a finding. An uncited source is recorded and
    # not flagged, which is a change made after the first real round: both
    # answers in it hedged rather than answering, cited nothing, and so had
    # every source uncited. That produced an auffällig on ordinary behaviour,
    # alongside the ablehnung finding the same hedge already caused — one fact,
    # two findings — and it buried the error class this check exists for, which
    # is a [3] against two sources.
    #
    # The count stays in belege, so the trend report can still ask how often
    # answers ignore their context. It just does not send anybody to read one.
    if dangling:
        return CheckOutcome(MARKER_AUSRICHTUNG, NICHT_AUSGERICHTET, auffaellig=True, belege=belege)
    return CheckOutcome(MARKER_AUSRICHTUNG, AUSGERICHTET, auffaellig=False, belege=belege)


# ── 4.4: does it say it does not know? ──────────────────────────────

ABLEHNUNG = "ablehnung"
KORREKT_ABGELEHNT = "korrekt abgelehnt"
NICHT_ABGELEHNT = "nicht abgelehnt"
ABLEHNUNG_UNERWARTET = "unerwartet abgelehnt"
# The fourth state, and the one that was missing: an ordinary question that was
# answered. It used to report "korrekt abgelehnt", which says the opposite of
# what happened and contradicted its own evidence — `abgelehnt: false` under a
# verdict reading "correctly refused". A reviewer stops on that every time.
KEINE_ABLEHNUNG_ERWARTET = "keine Ablehnung erwartet"

# Exactly what services/explorer.py returns when nothing was retrieved. Copied
# deliberately rather than imported: the harness is a separate distribution and
# depends on nothing of SENTRA's. That makes this a contract the harness
# asserts about SENTRA's behaviour, and a test pins the string so rewording it
# over there fails here loudly rather than passing every Grenzfall in silence.
REFUSAL_TEXT = "Es wurden keine relevanten Dokumente gefunden."


def ablehnung(response: dict, *, grenzfall: bool) -> CheckOutcome:
    """Whether an out-of-corpus question was refused, and an ordinary one was not.

    4.4 is where the real risk sits: a system that invents an answer rather than
    saying it has nothing is worse than one that finds nothing. The Vorlage
    keeps Grenzfälle out of automated filtering entirely for that reason, so
    this never suppresses review — it says what happened so a reviewer arrives
    already knowing.

    The opposite direction is a finding too. An ordinary question that gets
    refused means retrieval returned nothing for something the corpus should
    cover.
    """
    text = (response.get("text") or "").strip()
    sources = response.get("sources") or []
    refused = text == REFUSAL_TEXT and not sources

    belege = {
        "grenzfall": grenzfall,
        "abgelehnt": refused,
        "anzahl_quellen": len(sources),
        "antwort_beginn": text[:120],
    }

    if grenzfall and refused:
        return CheckOutcome(ABLEHNUNG, KORREKT_ABGELEHNT, auffaellig=False, belege=belege)
    if grenzfall and not refused:
        return CheckOutcome(ABLEHNUNG, NICHT_ABGELEHNT, auffaellig=True, belege=belege)
    if refused:
        return CheckOutcome(ABLEHNUNG, ABLEHNUNG_UNERWARTET, auffaellig=True, belege=belege)
    return CheckOutcome(ABLEHNUNG, KEINE_ABLEHNUNG_ERWARTET, auffaellig=False, belege=belege)


# ── Truncation, which is not inconsistency ──────────────────────────

ABSCHNEIDUNG = "abschneidung"
VOLLSTAENDIG = "vollständig"
ABGESCHNITTEN = "abgeschnitten"


def abschneidung(response: dict) -> CheckOutcome:
    """Whether the model stopped or ran out of room.

    A Fachfrage generates at 2048 tokens and an Überblick at 3072. An answer
    cut off at the ceiling reads exactly like an inconsistent one when all you
    can see is the text, and would be filed against the model. It is a finding
    against a configured limit, which is a different thing and a different fix.

    Absent finish_reason means the call was made without the debug flag, which
    is not a failure of the answer.
    """
    finish_reason = response.get("finish_reason")
    if finish_reason is None:
        return CheckOutcome(
            ABSCHNEIDUNG,
            NICHT_PRUEFBAR,
            auffaellig=False,
            belege={"grund": "Die Antwort wurde ohne debug-Flag abgerufen."},
        )

    belege = {"finish_reason": finish_reason, "laenge": len(response.get("text") or "")}
    if finish_reason == "length":
        return CheckOutcome(ABSCHNEIDUNG, ABGESCHNITTEN, auffaellig=True, belege=belege)
    return CheckOutcome(ABSCHNEIDUNG, VOLLSTAENDIG, auffaellig=False, belege=belege)


# ── The cheap half of 4.1 ───────────────────────────────────────────

WIEDERHOLBARKEIT = "wiederholbarkeit"
IDENTISCH = "identisch"
ABWEICHEND = "abweichend"


def wiederholbarkeit(texts: list[str]) -> CheckOutcome:
    """Whether repeats of the same prompt came back identical.

    At temperature 0.1 they often do, and when they do 4.1 is answered without
    spending a judge call on it. This never replaces the judge: identical text
    proves consistency, differing text proves nothing at all, because the
    Vorlage asks whether Kernaussage, Zahlen or Quellen differ — not whether
    the wording does. So "abweichend" is not a finding on its own; it is the
    signal that this case needs the judge.
    """
    unique = {text.strip() for text in texts}
    belege = {
        "anzahl_laeufe": len(texts),
        "verschiedene_antworten": len(unique),
        "laengen": [len(text) for text in texts],
    }

    if len(texts) < 2:
        return CheckOutcome(
            WIEDERHOLBARKEIT,
            NICHT_PRUEFBAR,
            auffaellig=False,
            belege={"grund": "Weniger als zwei Wiederholungen vorhanden."},
        )
    if len(unique) == 1:
        return CheckOutcome(WIEDERHOLBARKEIT, IDENTISCH, auffaellig=False, belege=belege)
    # Not auffällig: differing wording is exactly what the judge exists to read,
    # and flagging it here would send every case to a human for being phrased
    # differently twice.
    return CheckOutcome(WIEDERHOLBARKEIT, ABWEICHEND, auffaellig=False, belege=belege)
