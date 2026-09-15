"""Tests for metadata extraction from Bundestag documents."""

from sentra.ingestion.metadata import (
    _deduplicate_title,
    _extract_aktenzeichen,
    _extract_completion_date,
    _extract_document_type,
    _extract_fachbereich,
    _extract_title,
    _format_az,
    _normalize_az,
    _normalize_fachbereich_number,
    _normalize_german_date,
    _parse_pdf_date,
    extract_metadata,
)

# ---------------------------------------------------------------------------
# Aktenzeichen extraction
# ---------------------------------------------------------------------------


class TestExtractAktenzeichen:
    def test_from_body_label(self):
        md = "Aktenzeichen: WD 2 - 3000 - 029/25\nSome text"
        assert _extract_aktenzeichen(md, "", "doc.pdf") == "WD 2 - 3000 - 029/25"

    def test_from_body_label_extra_spaces(self):
        md = "Aktenzeichen: WD  3  -  3000  -  100/23\nSome text"
        assert _extract_aktenzeichen(md, "", "doc.pdf") == "WD 3 - 3000 - 100/23"

    def test_from_furniture(self):
        furniture = "Seite 1 WD 6 - 3000 - 052/24 Footer text"
        assert _extract_aktenzeichen("", furniture, "doc.pdf") == "WD 6 - 3000 - 052/24"

    def test_from_furniture_eu(self):
        furniture = "EU 6 - 3000 - 012/25"
        assert _extract_aktenzeichen("", furniture, "doc.pdf") == "EU 6 - 3000 - 012/25"

    def test_from_filename(self):
        assert _extract_aktenzeichen("", "", "WD 9-100-21.pdf") == "WD 9 - 3000 - 100/21"

    def test_from_filename_no_space(self):
        assert _extract_aktenzeichen("", "", "WD9-100-21.pdf") == "WD 9 - 3000 - 100/21"

    def test_from_filename_double_space(self):
        """Used to come out as "WD  9 - 3000 - 100/21".

        The filename branch only inserted a missing space and never collapsed
        a run of them, so a filename like this produced a malformed
        Aktenzeichen. Downstream that also cost the Fachbereich its name,
        because the lookup splits on " - " and "WD  9" is not a key.
        No filename in the current corpus has one, so nothing already indexed
        changes; it is the branches agreeing that matters.
        """
        assert _extract_aktenzeichen("", "", "WD  9-100-21.pdf") == "WD 9 - 3000 - 100/21"

    def test_from_filename_tab(self):
        assert _extract_aktenzeichen("", "", "WD\t9-100-21.pdf") == "WD 9 - 3000 - 100/21"

    def test_from_furniture_extra_spaces(self):
        assert (
            _extract_aktenzeichen("", "WD  6  -  3000  -  052/24", "doc.pdf")
            == "WD 6 - 3000 - 052/24"
        )

    def test_body_takes_priority_over_furniture(self):
        md = "Aktenzeichen: WD 3 - 3000 - 029/23"
        furniture = "WD 9 - 3000 - 999/99"
        assert _extract_aktenzeichen(md, furniture, "doc.pdf") == "WD 3 - 3000 - 029/23"

    def test_returns_empty_when_nothing_found(self):
        assert _extract_aktenzeichen("just some text", "", "random.pdf") == ""


# ---------------------------------------------------------------------------
# Fachbereich extraction
# ---------------------------------------------------------------------------


class TestExtractFachbereich:
    def test_from_body_label(self):
        md = "Fachbereich: WD 9: Gesundheit, Familie, Senioren, Frauen und Jugend\n"
        num, name = _extract_fachbereich(md, "", "")
        assert num == "WD 9"
        assert name == "Gesundheit, Familie, Senioren, Frauen und Jugend"

    def test_from_furniture(self):
        furniture = "Fachbereich WD 6 (Arbeit und Soziales)"
        num, name = _extract_fachbereich("", furniture, "")
        assert num == "WD 6"
        assert name == "Arbeit und Soziales"

    def test_from_aktenzeichen_lookup(self):
        num, name = _extract_fachbereich("", "", "WD 3 - 3000 - 029/23")
        assert num == "WD 3"
        assert name == "Verfassung und Verwaltung"

    def test_eu_fachbereich(self):
        num, name = _extract_fachbereich("", "", "EU 6 - 3000 - 012/25")
        assert num == "EU 6"
        assert name == "Fachbereich Europa"

    def test_returns_empty_when_nothing_found(self):
        assert _extract_fachbereich("", "", "") == ("", "")

    def test_number_spacing_normalized_from_body(self):
        md = "Fachbereich:  WD  9: Gesundheit, Familie\n"
        number, _ = _extract_fachbereich(md, "", "")
        assert number == "WD 9"

    def test_number_spacing_normalized_from_aktenzeichen(self):
        """A messy number here would miss the name lookup entirely."""
        number, name = _extract_fachbereich("", "", "WD  3 - 3000 - 029/23")
        assert number == "WD 3"
        assert name == "Verfassung und Verwaltung"


# ---------------------------------------------------------------------------
# Document type extraction
# ---------------------------------------------------------------------------


class TestExtractDocumentType:
    def test_from_label(self):
        assert _extract_document_type("Dokumententyp: Kurzinformation\n") == "Kurzinformation"

    def test_from_label_with_extra(self):
        assert _extract_document_type("Dokumententyp: Sachstand  \n") == "Sachstand"

    def test_from_header_area(self):
        md = "# Wissenschaftliche Dienste\n\n## Ausarbeitung\n\nSome content..."
        assert _extract_document_type(md) == "Ausarbeitung"

    def test_dokumentation(self):
        md = "# Dokumentation\n\nContent here"
        assert _extract_document_type(md) == "Dokumentation"

    def test_fallback_sonstiges(self):
        assert _extract_document_type("No known type here at all") == "Sonstiges"


# ---------------------------------------------------------------------------
# Title extraction
# ---------------------------------------------------------------------------


class TestExtractTitle:
    def test_from_label(self):
        md = "Titel: Ausnahmen von der Visumspflicht\nSome text"
        assert _extract_title(md) == "Ausnahmen von der Visumspflicht"

    def test_from_heading_skips_boilerplate(self):
        md = (
            "# Wissenschaftliche Dienste\n"
            "## Deutscher Bundestag\n"
            "## Sachstand\n"
            "## Regelungen zur Immunität von Abgeordneten\n"
            "Some body text"
        )
        assert _extract_title(md) == "Regelungen zur Immunität von Abgeordneten"

    def test_skips_short_headings(self):
        md = "# Hi\n## A real title that is long enough\n"
        assert _extract_title(md) == "A real title that is long enough"

    def test_skips_aktenzeichen_heading(self):
        md = "## Aktenzeichen: WD 3 - 029/23\n## Der eigentliche Titel des Dokuments\n"
        assert _extract_title(md) == "Der eigentliche Titel des Dokuments"

    def test_fallback_unbekannter_titel(self):
        assert _extract_title("No headings here, just text.") == "Unbekannter Titel"

    def test_deduplication_applied(self):
        md = "Titel: Regelungen zur Immunität Regelungen zur Immunität\n"
        assert _extract_title(md) == "Regelungen zur Immunität"


# ---------------------------------------------------------------------------
# Title deduplication (Docling bug)
# ---------------------------------------------------------------------------


class TestDeduplicateTitle:
    def test_duplicated(self):
        assert _deduplicate_title("Foo Bar Baz Foo Bar Baz") == "Foo Bar Baz"

    def test_not_duplicated(self):
        assert _deduplicate_title("Foo Bar Baz Qux") == "Foo Bar Baz Qux"

    def test_short_title_unchanged(self):
        assert _deduplicate_title("Foo Foo") == "Foo Foo"

    def test_single_word(self):
        assert _deduplicate_title("Immunität") == "Immunität"

    def test_odd_word_count(self):
        assert _deduplicate_title("A B C D E") == "A B C D E"


# ---------------------------------------------------------------------------
# PDF date parsing
# ---------------------------------------------------------------------------


class TestParsePdfDate:
    def test_standard_format(self):
        assert _parse_pdf_date("D:20231206120000+01'00'") == "2023-12-06"

    def test_without_prefix(self):
        assert _parse_pdf_date("20250703143000") == "2025-07-03"

    def test_short_string(self):
        assert _parse_pdf_date("D:2023") == ""

    def test_empty(self):
        assert _parse_pdf_date("") == ""

    def test_non_numeric(self):
        assert _parse_pdf_date("D:notadate") == ""


# ---------------------------------------------------------------------------
# German date normalization
# ---------------------------------------------------------------------------


class TestNormalizeGermanDate:
    def test_dd_mm_yyyy(self):
        assert _normalize_german_date("06.12.2023") == "2023-12-06"

    def test_d_mm_yyyy(self):
        assert _normalize_german_date("3.07.2025") == "2025-07-03"

    def test_german_month_name(self):
        assert _normalize_german_date("3. Juli 2025") == "2025-07-03"

    def test_german_month_name_long(self):
        assert _normalize_german_date("28. September 2024") == "2024-09-28"

    def test_german_month_maerz(self):
        assert _normalize_german_date("15. März 2024") == "2024-03-15"

    def test_already_iso(self):
        assert _normalize_german_date("2023-12-06") == "2023-12-06"

    def test_unknown_format_passthrough(self):
        assert _normalize_german_date("something weird") == "something weird"


# ---------------------------------------------------------------------------
# Completion date extraction (priority order)
# ---------------------------------------------------------------------------


class TestExtractCompletionDate:
    def test_pdf_metadata_takes_priority(self):
        md = "Abschluss der Arbeit: 3. Juli 2025"
        furniture = "WD 6 - 3000 - 052/24 (06.12.2023)"
        pdf_meta = {"CreationDate": "D:20250101120000"}
        assert _extract_completion_date(md, furniture, pdf_meta) == "2025-01-01"

    def test_body_label_second(self):
        md = "Abschluss der Arbeit: 28. Juli 2025"
        assert _extract_completion_date(md, "", {}) == "2025-07-28"

    def test_furniture_date_third(self):
        furniture = "WD 6 - 3000 - 052/24 (06.12.2023)"
        assert _extract_completion_date("", furniture, {}) == "2023-12-06"

    def test_returns_empty_when_nothing(self):
        assert _extract_completion_date("no date here", "", {}) == ""


# ---------------------------------------------------------------------------
# Normalize AZ
# ---------------------------------------------------------------------------


class TestNormalizeFachbereichNumber:
    """The single normalizer behind five former copies of the same re.sub.

    Three of them handled a Fachbereich number pulled out of text and two an
    Aktenzeichen prefix, which is the same thing, so they collapse into one
    function rather than one per call site.
    """

    def test_already_canonical(self):
        assert _normalize_fachbereich_number("WD 9") == "WD 9"

    def test_collapses_a_run_of_spaces(self):
        assert _normalize_fachbereich_number("WD   9") == "WD 9"

    def test_inserts_a_missing_space(self):
        assert _normalize_fachbereich_number("WD9") == "WD 9"

    def test_collapses_tabs(self):
        assert _normalize_fachbereich_number("WD\t9") == "WD 9"

    def test_strips_the_edges(self):
        assert _normalize_fachbereich_number("  WD 9  ") == "WD 9"

    def test_two_digit_number(self):
        assert _normalize_fachbereich_number("WD10") == "WD 10"

    def test_eu(self):
        assert _normalize_fachbereich_number("EU6") == "EU 6"

    def test_leaves_unrecognised_text_alone_apart_from_whitespace(self):
        assert _normalize_fachbereich_number("  etwas  anderes ") == "etwas anderes"


class TestFormatAz:
    """The single place that knows an Aktenzeichen's shape."""

    def test_assembles(self):
        assert _format_az("WD 2", "029/25") == "WD 2 - 3000 - 029/25"

    def test_normalizes_the_number_it_is_given(self):
        assert _format_az("WD  2", "029/25") == "WD 2 - 3000 - 029/25"
        assert _format_az("EU6", "012/25") == "EU 6 - 3000 - 012/25"

    def test_round_trips_through_normalize_az(self):
        """Whatever _format_az builds, _normalize_az leaves alone."""
        built = _format_az("WD  7", "045/22")
        assert _normalize_az(built) == built


class TestNormalizeAz:
    def test_normalizes_spacing(self):
        assert _normalize_az("WD  3  -  3000  -  029/23") == "WD 3 - 3000 - 029/23"

    def test_already_normalized(self):
        assert _normalize_az("WD 3 - 3000 - 029/23") == "WD 3 - 3000 - 029/23"


# ---------------------------------------------------------------------------
# Full extract_metadata integration
# ---------------------------------------------------------------------------


class TestExtractMetadata:
    def test_typical_ausarbeitung(self):
        md = (
            "# Wissenschaftliche Dienste\n"
            "## Ausarbeitung\n"
            "Titel: Regelungen zur Immunität von Abgeordneten\n"
            "Aktenzeichen: WD 3 - 3000 - 029/23\n"
            "Abschluss der Arbeit: 3. Juli 2025\n"
            "Fachbereich: WD 3: Verfassung und Verwaltung\n"
            "Dokumententyp: Ausarbeitung\n\n"
            "Die Immunität von Abgeordneten ist in Artikel 46 des Grundgesetzes geregelt. "
            "Sie dient dem Schutz der Funktionsfähigkeit des Parlaments und schützt "
            "Abgeordnete vor strafrechtlicher Verfolgung während ihrer Mandatszeit."
        )
        result = extract_metadata(md, "", "WD 3-029-23.pdf")
        assert result.aktenzeichen == "WD 3 - 3000 - 029/23"
        assert result.fachbereich_number == "WD 3"
        assert result.fachbereich == "Verfassung und Verwaltung"
        assert result.document_type == "Ausarbeitung"
        assert result.title == "Regelungen zur Immunität von Abgeordneten"
        assert result.completion_date == "2025-07-03"
        assert result.language == "de"
        assert result.source_file == "WD 3-029-23.pdf"

    def test_kurzinformation_from_furniture(self):
        md = "# Kurzinformation\n\nShort content about a topic that is relevant to parliament."
        furniture = "Fachbereich WD 6 (Arbeit und Soziales) WD 6 - 3000 - 052/24 (06.12.2023)"
        result = extract_metadata(md, furniture, "WD 6-052-24.pdf")
        assert result.aktenzeichen == "WD 6 - 3000 - 052/24"
        assert result.fachbereich_number == "WD 6"
        assert result.fachbereich == "Arbeit und Soziales"
        assert result.document_type == "Kurzinformation"
        assert result.completion_date == "2023-12-06"

    def test_english_doc_detected(self):
        md = (
            "# Sachstand\n"
            "Titel: International Regulations on Diplomatic Immunity\n\n"
            "The Vienna Convention on Diplomatic Relations of 1961 codifies the "
            "longstanding practice of diplomatic immunity. It establishes a framework "
            "for diplomatic relations between independent countries and aims to ensure "
            "the development of friendly relations among nations."
        )
        result = extract_metadata(md, "", "WD 2-027-25_EN.pdf")
        assert result.language == "en"
