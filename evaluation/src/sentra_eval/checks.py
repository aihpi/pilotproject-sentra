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
