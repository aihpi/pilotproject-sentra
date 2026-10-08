"""Reading the Word table the WD reviewers fill in.

Not one of our templates. The reviewers were sent their own form
("Test-Template für die Prüferinnen und Prüfer", 21.09.2026) before ours
existed: a document with one table, a row per text passage from a paper they
wrote, and the columns

  Test-ID | Ausgangsfrage | Referenzquelle(korrekt) | Referenzquelle | Referenzquelle (themat. …)

Two of those headers do not say what the column holds. "Referenzquelle(korrekt)"
is the passage itself, which is what the answer should say; "Referenzquelle" is
the paper it comes from. The reader goes by what the reviewers actually put in
them, and matches the headers only to find the columns.

What it does beyond copying cells, and why (#242):

  one case per question   the Ausgangsfrage cell usually holds an "Allgemein:"
                          and a "Konkret:" question. Measured separately, the
                          pair shows whether phrasing changes what is found
  category from the paper there is no category column; the correct source's
                          Fachbereich decides
  canonical Aktenzeichen  reviewers write both "WD 4 - 3000 - 115/22" and the
                          file name "WD-6-054-24.pdf"; the checks need one
                          spelling and one Aktenzeichen, so the first is taken
  the reviewer's ID       is not a Test-ID, which the backend allocates. It goes
                          into grund_fuer_aufnahme so a case can be traced back
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import IO, Any

from sentra_eval.categories import category_for_fachbereich
from sentra_eval.checks import normalise_aktenzeichen
from sentra_eval.vorlagen import VorlageError, _check_required, _require_docx

_DASH = r"\s*[-–—]\s*"
_AZ_FULL_RE = re.compile(rf"\b(WD|EU)\s*(\d+){_DASH}3000{_DASH}(\d+)\s*/\s*(\d+)", re.IGNORECASE)
_AZ_FILE_RE = re.compile(r"\b(WD|EU)[\s\-]*(\d+)-(\d+)-(\d+)\b", re.IGNORECASE)

_MARKER_RE = re.compile(r"\b(Allgemein|Konkret)\s*:", re.IGNORECASE)

# Normalised header → what the column holds. Normalised by dropping all
# whitespace, because "Referenzquelle(korrekt)" and "Referenzquelle (korrekt)"
# are the same header typed twice.
_PRUEFER_ID = "pruefer_id"
_FALSCH_PREFIX = "referenzquelle(thematisch"
_COLUMNS = {
    "test-id": _PRUEFER_ID,
    "ausgangsfrage": "ausgangsfrage",
    "referenzquelle(korrekt)": "erwartete_antwort",
    "referenzquelle": "referenz_korrekt",
}
_REQUIRED = ("ausgangsfrage", "erwartete_antwort", "referenz_korrekt")


def read_document(source: Path | IO[bytes], *, name: str = "") -> list[dict[str, Any]]:
    """A filled reviewer table as case entries, ready for `yaml_io.validate`.

    Takes a path or an open stream, like `vorlagen.read_workbook`, and for the
    same reason: the upload endpoint has bytes and no file.
    """
    _require_docx()
    from docx import Document

    label = name or (source.name if isinstance(source, Path) else "Die Datei")
    document = Document(source)

    table, columns = _find_table(document, label)

    entries: list[dict[str, Any]] = []
    for row_number, row in enumerate(table.rows[1:], start=2):
        cells = [cell.text for cell in row.cells]
        werte = {key: _clean(cells[i]) if i < len(cells) else "" for i, key in columns.items()}
        if not any(werte.values()):
            continue
        entries.extend(_entries_for_row(werte, row_number, label))

    return entries


def _find_table(document: Any, label: str) -> tuple[Any, dict[int, str]]:
    for table in document.tables:
        if not table.rows:
            continue
        header = [re.sub(r"\s+", "", cell.text).casefold() for cell in table.rows[0].cells]
        columns: dict[int, str] = {}
        for index, title in enumerate(header):
            if title.startswith(_FALSCH_PREFIX):
                columns[index] = "referenz_falsch"
            elif title in _COLUMNS:
                columns[index] = _COLUMNS[title]
        if "ausgangsfrage" not in columns.values():
            continue

        fehlend = [key for key in _REQUIRED if key not in columns.values()]
        if fehlend:
            raise VorlageError(
                f"{label}: der Tabelle fehlen Spalten für {', '.join(fehlend)}. "
                "Wurde die Kopfzeile der Prüfer-Vorlage verändert?"
            )
        return table, columns

    raise VorlageError(
        f"{label}: keine Tabelle mit einer Spalte „Ausgangsfrage“ gefunden. "
        "Ist das die ausgefüllte Prüfer-Vorlage?"
    )


def _entries_for_row(werte: dict[str, str], row_number: int, label: str) -> list[dict[str, Any]]:
    pruefer_id = re.sub(r"\s+", "", werte.get(_PRUEFER_ID, ""))
    where = f"{label}, Zeile {row_number}" + (f" ({pruefer_id})" if pruefer_id else "")

    korrekt_az = first_aktenzeichen(werte["referenz_korrekt"])
    falsch_az = first_aktenzeichen(werte.get("referenz_falsch", ""))

    kategorie = category_for_fachbereich(korrekt_az)
    if kategorie is None:
        raise VorlageError(
            f"{where}: aus der Referenzquelle lässt sich keine Kategorie ableiten"
            + (
                f" (Fachbereich von {korrekt_az} hat keine)."
                if korrekt_az
                else ", weil sie kein Aktenzeichen enthält."
            )
        )

    if (
        korrekt_az
        and falsch_az
        and normalise_aktenzeichen(korrekt_az) == normalise_aktenzeichen(falsch_az)
    ):
        raise VorlageError(
            f"{where}: die thematisch ähnliche Quelle ist dieselbe Arbeit wie die korrekte "
            f"({korrekt_az}). Die Quellenprüfung könnte so nie bestanden werden."
        )

    fragen = split_questions(werte["ausgangsfrage"])
    if not fragen:
        raise VorlageError(f"{where}: Ausgangsfrage fehlt.")

    entries = []
    for art, frage in fragen:
        herkunft = ", ".join(part for part in (pruefer_id or f"Zeile {row_number}", art) if part)
        entry: dict[str, Any] = {
            "kategorie": kategorie.value,
            "ausgangsfrage": frage,
            "abteilung": "",
            "erwartete_antwort": werte["erwartete_antwort"],
            "referenz_korrekt": werte["referenz_korrekt"],
            "referenz_korrekt_az": korrekt_az,
            "referenz_falsch": werte.get("referenz_falsch", ""),
            "referenz_falsch_az": falsch_az,
            "grund_fuer_aufnahme": f"Prüfer-Vorlage ({herkunft})",
            "grenzfall": False,
            "status": "entwurf",
        }
        _check_required(entry, row_number, label)
        entries.append(entry)
    return entries


def split_questions(text: str) -> list[tuple[str, str]]:
    """The questions in an Ausgangsfrage cell, each with its marker.

    A cell without markers is one question with an empty marker. Several
    questions under one marker stay together: the reviewer grouped them.
    """
    parts = _MARKER_RE.split(text)
    # re.split with one group alternates text and marker: [before, m1, t1, m2, t2, ...]
    fragen = []
    vorher = _clean(parts[0]).replace("\n", " ")
    if vorher:
        fragen.append(("", vorher))
    for marker, frage in zip(parts[1::2], parts[2::2], strict=True):
        frage = _clean(frage).replace("\n", " ")
        if frage:
            fragen.append((marker.capitalize(), frage))
    return fragen


def first_aktenzeichen(text: str) -> str:
    """The first Aktenzeichen in a cell, as "WD 4 - 3000 - 115/22"; "" if none."""
    candidates = [
        (m.start(), m.group(1), m.group(2), m.group(3), m.group(4))
        for pattern in (_AZ_FULL_RE, _AZ_FILE_RE)
        for m in pattern.finditer(text)
    ]
    if not candidates:
        return ""
    _, reihe, fachbereich, nummer, jahr = min(candidates)
    return f"{reihe.upper()} {int(fachbereich)} - 3000 - {nummer}/{jahr}"


def _clean(text: str) -> str:
    """Whitespace tidied line by line, blank lines dropped.

    Reviewers space questions apart with empty paragraphs; those are layout,
    not content.
    """
    lines = (re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)
