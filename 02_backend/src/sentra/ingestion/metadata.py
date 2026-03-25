import logging
import re
from dataclasses import dataclass
from datetime import datetime

from langdetect import DetectorFactory, detect

logger = logging.getLogger(__name__)

# Ensure reproducible language detection results
DetectorFactory.seed = 0

# Mapping of WD/EU department numbers to full names
FACHBEREICH_NAMES: dict[str, str] = {
    "WD 1": "Geschichte, Zeitgeschichte und Politik",
    "WD 2": "Auswärtiges, Völkerrecht, wirtschaftliche Zusammenarbeit und Entwicklung, Verteidigung, Menschenrechte und humanitäre Hilfe",
    "WD 3": "Verfassung und Verwaltung",
    "WD 4": "Haushalt und Finanzen",
    "WD 5": "Wirtschaft und Verkehr, Ernährung, Landwirtschaft und Verbraucherschutz",
    "WD 6": "Arbeit und Soziales",
    "WD 7": "Zivil-, Straf- und Verfahrensrecht, Bau und Stadtentwicklung",
    "WD 8": "Umwelt, Naturschutz, Reaktorsicherheit, Bildung und Forschung",
    "WD 9": "Gesundheit, Familie, Senioren, Frauen und Jugend",
    "WD 10": "Kultur, Medien und Sport",
    "EU 6": "Fachbereich Europa",
}

DOCUMENT_TYPES = [
    "Ausarbeitung",
    "Sachstand",
    "Kurzinformation",
    "Dokumentation",
]

# --- Regexes for furniture layer (page headers/footers) ---

# Aktenzeichen: "WD 2 - 3000 - 029/25" or "EU 6 - 3000 - 012/25"
_AZ_RE = re.compile(r"((?:WD|EU)\s+\d+)\s*-\s*3000\s*-\s*(\d+/\d+)")

# Date in parentheses after Aktenzeichen: "(06.12.2023)" or "(28. Juli 2025)"
_FOOTER_DATE_RE = re.compile(
    r"(?:WD|EU)\s+\d+\s*-\s*3000\s*-\s*\d+/\d+\s*\(([^)]+)\)"
)

# Fachbereich with full name: "Fachbereich WD 6 (Arbeit und Soziales)"
_FB_FULL_RE = re.compile(
    r"Fachbereich\s+((?:WD|EU)\s+\d+)\s*\(([^)]+)\)"
)

# --- Regexes for body Markdown ---

# Labeled Aktenzeichen: "Aktenzeichen: WD 2 - 3000 - 029/25"
_AZ_LABELED_RE = re.compile(
    r"Aktenzeichen:\s*((?:WD|EU)\s+\d+\s*-\s*3000\s*-\s*\d+/\d+)"
)

# Labeled completion date: "Abschluss der Arbeit: 3. Juli 2025"
_DATE_LABELED_RE = re.compile(
    r"Abschluss der Arbeit:\s*(.+?)(?=\s*(?:\(?zugleich|Fachbereich:|$))"
)

# Labeled Fachbereich: "Fachbereich: WD 9: Gesundheit, ..."
_FB_LABELED_RE = re.compile(
    r"Fachbereich:\s*((?:WD|EU)\s+\d+):\s*(.+?)(?:\n|$)"
)

# Dokumententyp label: "Dokumententyp: Kurzinformation"
_DOKUMENTENTYP_RE = re.compile(r"Dokumententyp:\s*(.+?)(?:\s{2,}|\n|$)")

# Titel label: "Titel: Ausnahmen von der..."
_TITEL_RE = re.compile(r"Titel:\s*(.+?)(?:\s{2,}|\n|$)")

# Filename extraction: "WD 9-100-21" from "WD 9-100-21.pdf"
_FILENAME_RE = re.compile(r"((?:WD|EU)\s*\d+)-(\d+)-(\d+)")

# Filename language hint: "_EN.pdf" or "_DE.pdf"
_FILENAME_LANG_RE = re.compile(r"_([A-Z]{2})\.pdf$", re.IGNORECASE)


@dataclass
class DocumentMetadata:
    """Structured metadata extracted from a Bundestag WD document."""

    aktenzeichen: str
    fachbereich_number: str
    fachbereich: str
    document_type: str
    title: str
    completion_date: str
    language: str
    source_file: str


def extract_metadata(
    markdown: str, furniture_text: str, source_file: str, pdf_metadata: dict | None = None
) -> DocumentMetadata:
    """Extract structured metadata from a Bundestag document.

    Uses a multi-source approach:
    - Body markdown labeled fields (e.g., "Aktenzeichen: ...") — used by longer documents
    - Furniture text (page headers/footers) — reliable for all document types
    - PDF embedded metadata (CreationDate) — reliable primary source for dates
    - Filename as last-resort fallback for Aktenzeichen and language
    - Content-based language detection using langdetect
    """
    aktenzeichen = _extract_aktenzeichen(markdown, furniture_text, source_file)
    fachbereich_number, fachbereich = _extract_fachbereich(
        markdown, furniture_text, aktenzeichen
    )
    document_type = _extract_document_type(markdown)
    title = _extract_title(markdown)
    completion_date = _extract_completion_date(markdown, furniture_text, pdf_metadata or {})
    language = _detect_language(markdown, source_file)

    return DocumentMetadata(
        aktenzeichen=aktenzeichen,
        fachbereich_number=fachbereich_number,
        fachbereich=fachbereich,
        document_type=document_type,
        title=title,
        completion_date=completion_date,
        language=language,
        source_file=source_file,
    )


def _extract_aktenzeichen(
    markdown: str, furniture_text: str, source_file: str
) -> str:
    """Extract Aktenzeichen from body labels, furniture, or filename."""
    # 1. Labeled field in body: "Aktenzeichen: WD 2 - 3000 - 029/25"
    match = _AZ_LABELED_RE.search(markdown)
    if match:
        return _normalize_az(match.group(1))

    # 2. Furniture layer (page headers/footers)
    match = _AZ_RE.search(furniture_text)
    if match:
        fb = re.sub(r"\s+", " ", match.group(1).strip())
        return f"{fb} - 3000 - {match.group(2)}"

    # 3. Filename fallback: "WD 9-100-21.pdf"
    match = _FILENAME_RE.search(source_file)
    if match:
        fb = re.sub(r"(WD|EU)(\d)", r"\1 \2", match.group(1).strip())
        az = f"{fb} - 3000 - {match.group(2)}/{match.group(3)}"
        logger.info("Aktenzeichen derived from filename for %s: %s", source_file, az)
        return az

    logger.warning("Could not extract Aktenzeichen from %s", source_file)
    return ""


def _extract_fachbereich(
    markdown: str, furniture_text: str, aktenzeichen: str
) -> tuple[str, str]:
    """Extract Fachbereich number and name. Returns (number, full_name)."""
    # 1. Labeled field in body: "Fachbereich: WD 9: Gesundheit, ..."
    match = _FB_LABELED_RE.search(markdown)
    if match:
        number = re.sub(r"\s+", " ", match.group(1).strip())
        return number, match.group(2).strip()

    # 2. Furniture: "Fachbereich WD 6 (Arbeit und Soziales)"
    match = _FB_FULL_RE.search(furniture_text)
    if match:
        number = re.sub(r"\s+", " ", match.group(1).strip())
        return number, match.group(2).strip()

    # 3. Derive from Aktenzeichen prefix + lookup table
    if aktenzeichen:
        number = aktenzeichen.split(" - ")[0].strip()
        number = re.sub(r"\s+", " ", number)
        return number, FACHBEREICH_NAMES.get(number, number)

    return "", ""


def _extract_document_type(markdown: str) -> str:
    """Extract document type from Dokumententyp label or header content."""
    # Labeled: "Dokumententyp: Kurzinformation"
    match = _DOKUMENTENTYP_RE.search(markdown)
    if match:
        raw = match.group(1).strip()
        for dt in DOCUMENT_TYPES:
            if dt in raw:
                return dt

    # Search in first ~1500 chars for known types
    header = markdown[:1500]
    for doc_type in DOCUMENT_TYPES:
        if doc_type in header:
            return doc_type

    return "Sonstiges"


def _extract_title(markdown: str) -> str:
    """Extract the document title."""
    # Labeled: "Titel: Ausnahmen von der Visumspflicht..."
    match = _TITEL_RE.search(markdown)
    if match:
        return _deduplicate_title(match.group(1).strip())

    # Find first meaningful Markdown heading
    skip_lower = {
        "wissenschaftliche dienste",
        "aktenzeichen",
        "inhaltsverzeichnis",
        "dokumententyp",
        "deutscher bundestag",
    }
    for line in markdown.split("\n"):
        line = line.strip()
        if not line.startswith("#"):
            continue
        heading = line.lstrip("#").strip()
        if not heading or len(heading) < 5:
            continue
        heading_lower = heading.lower()
        if heading_lower in skip_lower:
            continue
        if any(dt.lower() in heading_lower for dt in DOCUMENT_TYPES):
            continue
        if heading_lower.startswith("aktenzeichen:"):
            continue
        return _deduplicate_title(heading)

    return "Unbekannter Titel"


def _extract_completion_date(markdown: str, furniture_text: str, pdf_metadata: dict) -> str:
    """Extract completion date, normalized to ISO format (YYYY-MM-DD).

    Priority:
    1. PDF embedded CreationDate (available in all documents)
    2. Body label: "Abschluss der Arbeit: 3. Juli 2025"
    3. Furniture: date after Aktenzeichen "(06.12.2023)"
    """
    # 1. PDF metadata CreationDate (most reliable, available everywhere)
    creation_date = pdf_metadata.get("CreationDate", "")
    if creation_date:
        parsed = _parse_pdf_date(creation_date)
        if parsed:
            return parsed

    # 2. Labeled field: "Abschluss der Arbeit: 3. Juli 2025"
    match = _DATE_LABELED_RE.search(markdown)
    if match:
        date_str = match.group(1).strip()
        date_str = re.sub(r"\s*\(.*$", "", date_str).strip()
        return _normalize_german_date(date_str)

    # 3. Furniture: date after Aktenzeichen "(06.12.2023)"
    match = _FOOTER_DATE_RE.search(furniture_text)
    if match:
        return _normalize_german_date(match.group(1).strip())

    return ""


# German month names to numbers
_GERMAN_MONTHS: dict[str, int] = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8,
    "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}


def _parse_pdf_date(raw: str) -> str:
    """Parse PDF date format 'D:YYYYMMDDHHmmSS+TZ' to ISO 'YYYY-MM-DD'."""
    # Strip the "D:" prefix if present
    s = raw.strip()
    if s.startswith("D:"):
        s = s[2:]
    # We only need the first 8 chars: YYYYMMDD
    if len(s) >= 8 and s[:8].isdigit():
        try:
            dt = datetime.strptime(s[:8], "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _normalize_german_date(date_str: str) -> str:
    """Normalize a German date string to ISO format (YYYY-MM-DD).

    Handles formats like:
    - "06.12.2023" (DD.MM.YYYY)
    - "3. Juli 2025" (D. MonthName YYYY)
    - "28. Juli 2025"
    """
    # Try DD.MM.YYYY
    match = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", date_str)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"

    # Try "D. MonthName YYYY"
    match = re.match(r"(\d{1,2})\.\s*(\w+)\s+(\d{4})", date_str)
    if match:
        day = int(match.group(1))
        month_name = match.group(2).lower()
        year = int(match.group(3))
        month = _GERMAN_MONTHS.get(month_name)
        if month:
            return f"{year:04d}-{month:02d}-{day:02d}"

    # Already ISO or unrecognized — return as-is
    return date_str


def _detect_language(markdown: str, source_file: str) -> str:
    """Detect document language from content, with filename as fallback.

    Primary: langdetect on body content (first ~2000 chars).
    Fallback: filename hint (e.g., '_EN.pdf' -> 'en').
    Default: 'de' (German) for Bundestag documents.
    """
    # Try content-based detection first
    sample_lines = []
    for line in markdown.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("<!--"):
            continue
        if line.startswith("|") or line.startswith("---"):
            continue
        sample_lines.append(line)
        if sum(len(line) for line in sample_lines) > 2000:
            break

    sample = " ".join(sample_lines)
    if len(sample) >= 50:
        try:
            return detect(sample)
        except Exception:
            logger.debug("langdetect failed for %s, trying filename", source_file)

    # Fallback: filename language hint (e.g., "_EN.pdf")
    match = _FILENAME_LANG_RE.search(source_file)
    if match:
        return match.group(1).lower()

    return "de"


def _normalize_az(raw: str) -> str:
    """Normalize Aktenzeichen spacing."""
    match = _AZ_RE.search(raw)
    if match:
        fb = re.sub(r"\s+", " ", match.group(1).strip())
        return f"{fb} - 3000 - {match.group(2)}"
    return raw.strip()


def _deduplicate_title(title: str) -> str:
    """Fix Docling duplication: 'Foo Bar Foo Bar' -> 'Foo Bar'."""
    words = title.split()
    mid = len(words) // 2
    if mid > 2 and words[:mid] == words[mid : 2 * mid]:
        return " ".join(words[:mid])
    return title
