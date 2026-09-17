"""The categories a test case can belong to.

One definition, because the Test-ID is built from the abbreviation and the
number is allocated per category. Adding a category here is the whole change;
nothing else holds a copy.

The three the Vorlage names by example are the starting set. It says explicitly
that cases are grouped "grob nach Kategorien" so that later evaluation can find
patterns per category, so this list is expected to grow as Hotline brings more
kinds of question in.
"""

from enum import StrEnum


class Kategorie(StrEnum):
    """Category abbreviation, as it appears inside a Test-ID."""

    GO = "GO"  # Geschäftsordnung
    GV = "GV"  # Gesetzgebungsverfahren
    AR = "AR"  # Abgeordnetenrechte


# The human-readable name, for reports that a reviewer reads rather than parses.
KATEGORIE_NAMEN: dict[Kategorie, str] = {
    Kategorie.GO: "Geschäftsordnung",
    Kategorie.GV: "Gesetzgebungsverfahren",
    Kategorie.AR: "Abgeordnetenrechte",
}
