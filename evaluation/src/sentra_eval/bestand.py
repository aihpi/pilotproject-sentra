"""Which documents SENTRA has indexed, by Aktenzeichen.

A case whose correct source is not indexed cannot be measured: SENTRA cannot
cite a document it does not have, so 4.3b reports a wrong source and the
retrieval check reports it as not found. Both read as SENTRA failing when the
gap is in the corpus. So approval asks first (#257).

Asked over HTTP, like everything else the harness wants from SENTRA, and kept
for a minute: the Testfälle table asks on every refresh, and the answer only
changes when somebody ingests.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

from sentra_eval.checks import normalise_aktenzeichen
from sentra_eval.config import get_eval_settings, sentra_headers

logger = logging.getLogger(__name__)

DOCUMENTS_LIST_ENDPOINT = "/api/documents"
CACHE_SECONDS = 60.0


@dataclass(frozen=True)
class Bestand:
    """The indexed Aktenzeichen, or why they could not be read."""

    aktenzeichen: frozenset[str] = field(default_factory=frozenset)
    # Empty when SENTRA answered. Set, the check cannot be made, and approval
    # is refused rather than allowed unchecked.
    fehler: str = ""

    @property
    def erreichbar(self) -> bool:
        return not self.fehler

    def enthaelt(self, aktenzeichen: str) -> bool:
        return normalise_aktenzeichen(aktenzeichen) in self.aktenzeichen


_cache: tuple[float, Bestand] | None = None


def fetch(client: httpx.Client | None = None, *, use_cache: bool = True) -> Bestand:
    """The current Bestand. Never raises: an unreachable SENTRA is a Bestand too."""
    global _cache
    now = time.monotonic()
    if use_cache and client is None and _cache and now - _cache[0] < CACHE_SECONDS:
        return _cache[1]

    settings = get_eval_settings()
    owned = client is None
    client = client or httpx.Client(
        base_url=settings.sentra_base_url, timeout=30.0, headers=sentra_headers(settings)
    )
    try:
        response = client.get(DOCUMENTS_LIST_ENDPOINT)
        response.raise_for_status()
        bestand = Bestand(
            aktenzeichen=frozenset(
                normalise_aktenzeichen(d.get("aktenzeichen", ""))
                for d in response.json()
                if d.get("aktenzeichen")
            )
        )
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Could not read the indexed documents from SENTRA: %s", exc)
        # Not cached, so the next request tries again rather than reporting a
        # minute-old outage.
        return Bestand(fehler="SENTRA ist nicht erreichbar, der Bestand kann nicht geprüft werden")
    finally:
        if owned:
            client.close()

    if owned:
        _cache = (now, bestand)
    return bestand


def clear_cache() -> None:
    global _cache
    _cache = None
