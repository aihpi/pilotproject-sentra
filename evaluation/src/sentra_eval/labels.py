"""The labels a test case carries, so a round can be broken down by them (#286).

Four dimensions, each answering a different question about a case:

  kategorie   where it comes from: a Fachbereich (FI for WD 4, …) or a Hotline
              topic (GO, GV, AR). The Vorlage's "Kategorie", shown as Bereich
  testart     what it is meant to test: the ordinary case, or one of the
              harder kinds the Vorlage asks to be built in on purpose (4.4)
  frageform   how it is asked: allgemein or konkret, as the reviewers write them
  herkunft    who wrote it

Kategorie and Testart are open lists. The built-in values are always offered;
a value somebody types in is offered for as long as at least one case uses it,
and disappears once none does. Nothing stores the list itself, so there is
nothing to clean up.
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from sentra_eval.categories import KATEGORIE_NAMEN
from sentra_eval.models import Case

# Value → the three letters a generated tag uses for it.
TESTARTEN: dict[str, str] = {
    "Regelfall": "REG",
    "Präzision": "PRZ",
    "Quellenwahl": "QLW",
    "Synthese": "SYN",
    "Grenzfall · außerhalb des Bestands": "GAB",
    "Grenzfall · mehrdeutig": "GMD",
    "Grenzfall · veraltet": "GVA",
    "Grenzfall · falsche Annahme": "GFA",
}

# The one Testart the checks depend on: a question the corpus holds nothing for,
# where SENTRA has to say so (4.4). It and the version's grenzfall flag are kept
# in step on drafts.
GRENZFALL_AUSSERHALB = "Grenzfall · außerhalb des Bestands"

FRAGEFORMEN: tuple[str, ...] = ("allgemein", "konkret")
# Each importer writes one of these, so all of them are offered (#300).
HERKUENFTE: tuple[str, ...] = (
    "Prüfer-Vorlage",
    "Erfassungsvorlage",
    "Hotline",
    "Feedback",
    "manuell",
)

# Short, because it is the first part of every generated tag and is stored in
# a String(8). Letters and digits only, so "FI-PRZ-003" stays readable.
KATEGORIE_PATTERN = re.compile(r"^[A-Z0-9]{1,8}$")


class LabelError(ValueError):
    """A label value that cannot be used."""


def normalise_kategorie(value: str) -> str:
    kategorie = value.strip().upper().replace(" ", "")
    if not KATEGORIE_PATTERN.fullmatch(kategorie):
        raise LabelError(
            f"Bereich „{value}“ geht nicht: ein bis acht Buchstaben oder Ziffern, "
            "z. B. FI oder WD3."
        )
    return kategorie


def kuerzel(testart: str) -> str:
    """The three letters for a Testart: the built-in one, or derived from the name."""
    if testart in TESTARTEN:
        return TESTARTEN[testart]
    ascii_only = unicodedata.normalize("NFKD", testart).encode("ascii", "ignore").decode()
    letters = re.sub(r"[^A-Za-z]", "", ascii_only).upper()
    return (letters[:3] or "XXX").ljust(3, "X")


def tag_prefix(kategorie: str, testart: str) -> str:
    """What a generated tag starts with: "FI-PRZ", or just "FI" without a Testart."""
    return f"{kategorie}-{kuerzel(testart)}" if testart else kategorie


def offered(session: Session) -> dict[str, list[str]]:
    """The values to offer per dimension: the built-in ones, then those in use."""
    in_use: dict[str, set[str]] = {"kategorie": set(), "testart": set(), "herkunft": set()}
    rows = session.execute(select(Case.kategorie, Case.testart, Case.herkunft)).all()
    for kategorie, testart, herkunft in rows:
        in_use["kategorie"].add(kategorie)
        in_use["testart"].add(testart)
        in_use["herkunft"].add(herkunft)

    def merged(builtin: list[str], used: set[str]) -> list[str]:
        return builtin + sorted(v for v in used if v and v not in builtin)

    return {
        "kategorie": merged([str(k) for k in KATEGORIE_NAMEN], in_use["kategorie"]),
        "testart": merged(list(TESTARTEN), in_use["testart"]),
        "frageform": list(FRAGEFORMEN),
        "herkunft": merged(list(HERKUENFTE), in_use["herkunft"]),
    }
