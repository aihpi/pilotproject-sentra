"""The categories a test case can belong to.

One definition, because the Test-ID is built from the abbreviation and the
number is allocated per category. Adding a category here is the whole change;
nothing else holds a copy.

The three the Vorlage names by example are the starting set. It says explicitly
that cases are grouped "grob nach Kategorien" so that later evaluation can find
patterns per category, so this list is expected to grow as Hotline brings more
kinds of question in.

FI and WI came in with the first cases written by the Wissenschaftliche
Dienste themselves (#242). Those are grouped by the Fachbereich whose paper
answers the question, which is how the people writing them think about it.
"""

import re
from enum import StrEnum


class Kategorie(StrEnum):
    """Category abbreviation, as it appears inside a Test-ID."""

    GO = "GO"  # Geschäftsordnung
    GV = "GV"  # Gesetzgebungsverfahren
    AR = "AR"  # Abgeordnetenrechte
    FI = "FI"  # Haushalt und Finanzen (WD 4)
    WI = "WI"  # Wirtschaft, Energie, Umwelt (WD 5)


# The human-readable name, for reports that a reviewer reads rather than parses.
KATEGORIE_NAMEN: dict[Kategorie, str] = {
    Kategorie.GO: "Geschäftsordnung",
    Kategorie.GV: "Gesetzgebungsverfahren",
    Kategorie.AR: "Abgeordnetenrechte",
    Kategorie.FI: "Haushalt und Finanzen",
    Kategorie.WI: "Wirtschaft, Energie, Umwelt",
}

# Only the Fachbereiche somebody has written cases for. A paper from any other
# one gets no category rather than a guessed one, so whoever imports it is
# asked to add it here.
FACHBEREICH_KATEGORIE: dict[str, Kategorie] = {
    "WD 4": Kategorie.FI,
    "WD 5": Kategorie.WI,
}

_FACHBEREICH_RE = re.compile(r"^\s*(WD|EU)[\s\-]*(\d+)", re.IGNORECASE)


def category_for_fachbereich(value: str) -> Kategorie | None:
    """The category for a Fachbereich, given it or an Aktenzeichen starting with it.

    Accepts "WD 4", "WD 4 - 3000 - 115/22" and the file-name spelling
    "WD-4-115-22" alike.
    """
    match = _FACHBEREICH_RE.match(value)
    if match is None:
        return None
    return FACHBEREICH_KATEGORIE.get(f"{match.group(1).upper()} {int(match.group(2))}")
