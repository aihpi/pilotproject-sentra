"""End-to-end metadata extraction from real PDFs.

These tests parse the actual 17 test PDFs with Docling and verify that
metadata extraction produces correct, user-visible information.

If metadata is wrong, everything downstream breaks — wrong titles in search
results, wrong fachbereich in filters, wrong dates in sorting.

Run:  uv run pytest tests/test_ingestion_e2e.py -v
      (takes ~30-60s due to Docling PDF parsing)
"""

import re
from datetime import date
from pathlib import Path

import pytest

from sentra.ingestion.chunker import chunk_document
from sentra.ingestion.metadata import (
    FACHBEREICH_NAMES,
    extract_metadata,
)
from sentra.ingestion.parser import parse_pdfs
from sentra.ingestion.urls import extract_urls
from tests.conftest import (
    DATA_DIR,
    GROUND_TRUTH,
    TOTAL_PDFS,
    VALID_DOCUMENT_TYPES,
    VALID_FACHBEREICH_NUMBERS,
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def parsed_docs():
    """Parse all test PDFs once for the entire module."""
    if not DATA_DIR.is_dir():
        pytest.skip(f"Test data directory not found: {DATA_DIR}")
    docs = parse_pdfs(str(DATA_DIR))
    assert len(docs) > 0, "Docling returned no parsed documents"
    return docs


@pytest.fixture(scope="module")
def extracted_metadata(parsed_docs):
    """Extract metadata from all parsed documents. Returns dict[filename → metadata]."""
    results = {}
    for doc in parsed_docs:
        meta = extract_metadata(doc.markdown, doc.furniture_text, doc.source_file, doc.pdf_metadata)
        results[doc.source_file] = meta
    return results


# ── Test: All PDFs are parsed ───────────────────────────────────────


class TestAllPdfsParsed:
    def test_all_pdfs_found(self, parsed_docs):
        """Every PDF in 03_data/Ausarbeitungen should be parsed successfully."""
        parsed_names = {doc.source_file for doc in parsed_docs}
        expected_names = set(GROUND_TRUTH.keys())
        missing = expected_names - parsed_names
        assert not missing, f"PDFs not parsed: {missing}"

    def test_correct_count(self, parsed_docs):
        assert len(parsed_docs) == TOTAL_PDFS

    def test_markdown_not_empty(self, parsed_docs):
        """Every document should produce non-empty markdown body."""
        for doc in parsed_docs:
            assert len(doc.markdown.strip()) > 100, (
                f"{doc.source_file}: markdown body is too short ({len(doc.markdown)} chars)"
            )


# ── Test: Aktenzeichen extraction ──────────────────────────────────


class TestAktenzeichenExtraction:
    """A user sees the Aktenzeichen as the unique document identifier.
    If it's wrong or missing, they can't find or cite the document."""

    def test_never_empty(self, extracted_metadata):
        for filename, meta in extracted_metadata.items():
            assert meta.aktenzeichen, f"{filename}: Aktenzeichen is empty"

    def test_correct_format(self, extracted_metadata):
        """Every Aktenzeichen must follow the standard pattern."""
        pattern = re.compile(r"^(WD|EU)\s+\d+\s+-\s+3000\s+-\s+\d+/\d+$")
        for filename, meta in extracted_metadata.items():
            assert pattern.match(meta.aktenzeichen), (
                f"{filename}: '{meta.aktenzeichen}' doesn't match expected AZ pattern"
            )

    def test_matches_ground_truth(self, extracted_metadata):
        """For PDFs where we know the exact AZ, verify it matches."""
        for filename, expected in GROUND_TRUTH.items():
            if filename not in extracted_metadata:
                continue
            meta = extracted_metadata[filename]

            if "aktenzeichen" in expected:
                assert meta.aktenzeichen == expected["aktenzeichen"], (
                    f"{filename}: expected AZ '{expected['aktenzeichen']}', got '{meta.aktenzeichen}'"
                )
            elif "aktenzeichen_startswith" in expected:
                assert meta.aktenzeichen.startswith(expected["aktenzeichen_startswith"]), (
                    f"{filename}: AZ '{meta.aktenzeichen}' doesn't start with '{expected['aktenzeichen_startswith']}'"
                )


# ── Test: Fachbereich extraction ───────────────────────────────────


class TestFachbereichExtraction:
    """Users filter by Fachbereich. If WD 6 document shows up under WD 3, the filter is broken."""

    def test_number_always_valid(self, extracted_metadata):
        for filename, meta in extracted_metadata.items():
            assert meta.fachbereich_number in VALID_FACHBEREICH_NUMBERS, (
                f"{filename}: fachbereich_number '{meta.fachbereich_number}' is not valid"
            )

    def test_name_not_empty(self, extracted_metadata):
        for filename, meta in extracted_metadata.items():
            assert meta.fachbereich, f"{filename}: fachbereich name is empty"

    def test_name_matches_lookup_table(self, extracted_metadata):
        """Fachbereich name should share its leading keyword with the canonical mapping.

        Note: Department names have changed over time (e.g., WD 5 was renamed),
        so we only check the first keyword matches, not the full string.
        """
        for filename, meta in extracted_metadata.items():
            expected_name = FACHBEREICH_NAMES.get(meta.fachbereich_number)
            if expected_name:
                # Both names should share the same leading keyword(s)
                actual_first = meta.fachbereich.lower().split(",")[0].split()[0]
                expected_first = expected_name.lower().split(",")[0].split()[0]
                assert actual_first == expected_first, (
                    f"{filename}: fachbereich '{meta.fachbereich}' first keyword doesn't match "
                    f"expected '{expected_name}' for {meta.fachbereich_number}"
                )

    def test_matches_ground_truth(self, extracted_metadata):
        for filename, expected in GROUND_TRUTH.items():
            if filename not in extracted_metadata:
                continue
            meta = extracted_metadata[filename]

            if "fachbereich_number" in expected:
                assert meta.fachbereich_number == expected["fachbereich_number"], (
                    f"{filename}: expected FB '{expected['fachbereich_number']}', got '{meta.fachbereich_number}'"
                )
            elif "fachbereich_number_in" in expected:
                assert meta.fachbereich_number in expected["fachbereich_number_in"], (
                    f"{filename}: FB '{meta.fachbereich_number}' not in {expected['fachbereich_number_in']}"
                )

    def test_fachbereich_consistent_with_aktenzeichen(self, extracted_metadata):
        """The fachbereich_number prefix should match the Aktenzeichen prefix."""
        for filename, meta in extracted_metadata.items():
            if not meta.aktenzeichen:
                continue
            az_prefix = meta.aktenzeichen.split(" - ")[0].strip()
            assert meta.fachbereich_number == az_prefix, (
                f"{filename}: AZ prefix '{az_prefix}' != fachbereich_number '{meta.fachbereich_number}'"
            )


# ── Test: Document type extraction ─────────────────────────────────


class TestDocumentTypeExtraction:
    """Users filter by document type. An incorrect type means the document
    won't appear when a user filters for it."""

    def test_always_valid_type(self, extracted_metadata):
        for filename, meta in extracted_metadata.items():
            assert meta.document_type in VALID_DOCUMENT_TYPES, (
                f"{filename}: document_type '{meta.document_type}' is not valid"
            )

    def test_never_empty(self, extracted_metadata):
        for filename, meta in extracted_metadata.items():
            assert meta.document_type, f"{filename}: document_type is empty"


# ── Test: Title extraction ─────────────────────────────────────────


class TestTitleExtraction:
    """The title is the most prominent text in search results.
    A bad title makes the app look broken."""

    def test_never_placeholder(self, extracted_metadata):
        """No document should have the fallback title."""
        for filename, meta in extracted_metadata.items():
            assert meta.title != "Unbekannter Titel", (
                f"{filename}: title fell through to placeholder 'Unbekannter Titel'"
            )

    def test_meaningful_length(self, extracted_metadata):
        """Titles should be long enough to be meaningful."""
        for filename, meta in extracted_metadata.items():
            assert len(meta.title) >= 10, (
                f"{filename}: title '{meta.title}' is too short to be useful"
            )

    def test_no_docling_duplication(self, extracted_metadata):
        """Docling sometimes duplicates titles: 'Foo Bar Foo Bar'. Check this is cleaned."""
        for filename, meta in extracted_metadata.items():
            words = meta.title.split()
            mid = len(words) // 2
            if mid > 2:
                assert words[:mid] != words[mid:2 * mid], (
                    f"{filename}: title '{meta.title}' appears to have Docling duplication"
                )

    def test_no_boilerplate_as_title(self, extracted_metadata):
        """Title should not be generic boilerplate."""
        boilerplate = {
            "wissenschaftliche dienste",
            "deutscher bundestag",
            "inhaltsverzeichnis",
        }
        for filename, meta in extracted_metadata.items():
            assert meta.title.lower() not in boilerplate, (
                f"{filename}: title '{meta.title}' is boilerplate, not an actual title"
            )


# ── Test: Completion date extraction ───────────────────────────────


class TestCompletionDateExtraction:
    """The date drives date-range filtering and sorting.
    Wrong dates means filter "2023" returns 2025 documents."""

    def test_never_empty(self, extracted_metadata):
        for filename, meta in extracted_metadata.items():
            assert meta.completion_date, f"{filename}: completion_date is empty"

    def test_valid_iso_format(self, extracted_metadata):
        """Every date must parse as a real ISO date."""
        for filename, meta in extracted_metadata.items():
            if not meta.completion_date:
                continue
            try:
                parsed = date.fromisoformat(meta.completion_date)
                # Sanity: year should be in a reasonable range
                assert 2015 <= parsed.year <= 2030, (
                    f"{filename}: date year {parsed.year} outside expected range"
                )
            except ValueError:
                pytest.fail(f"{filename}: '{meta.completion_date}' is not valid ISO date")

    def test_year_matches_filename_hint(self, extracted_metadata):
        """The year in the date should approximately match the filename's year hint."""
        for filename, expected in GROUND_TRUTH.items():
            if filename not in extracted_metadata:
                continue
            meta = extracted_metadata[filename]
            if not meta.completion_date or "year_hint" not in expected:
                continue
            parsed = date.fromisoformat(meta.completion_date)
            hint = expected["year_hint"]
            # Allow +-1 year tolerance (PDF creation date can differ from year in filename)
            assert abs(parsed.year - hint) <= 1, (
                f"{filename}: date year {parsed.year} doesn't match filename hint {hint} (+-1 tolerance)"
            )


# ── Test: Language detection ───────────────────────────────────────


class TestLanguageDetection:
    """One document is in English; all others are German."""

    def test_english_doc_detected(self, extracted_metadata):
        meta = extracted_metadata.get("WD 2-027-25_EN.pdf")
        if meta is None:
            pytest.skip("English PDF not in extracted metadata")
        assert meta.language == "en", (
            f"English document detected as '{meta.language}' instead of 'en'"
        )

    def test_german_docs_detected(self, extracted_metadata):
        for filename, expected in GROUND_TRUTH.items():
            if filename not in extracted_metadata:
                continue
            if expected.get("language") == "de":
                meta = extracted_metadata[filename]
                assert meta.language == "de", (
                    f"{filename}: expected 'de', detected '{meta.language}'"
                )

    def test_valid_language_code(self, extracted_metadata):
        for filename, meta in extracted_metadata.items():
            assert meta.language in ("de", "en"), (
                f"{filename}: unexpected language '{meta.language}'"
            )


# ── Test: Chunking produces reasonable output ──────────────────────


class TestChunkingRealDocs:
    """Every document should produce at least one chunk that gets indexed."""

    def test_every_doc_produces_chunks(self, parsed_docs):
        for doc in parsed_docs:
            meta = extract_metadata(doc.markdown, doc.furniture_text, doc.source_file, doc.pdf_metadata)
            chunks = chunk_document(doc.markdown, meta)
            assert len(chunks) > 0, f"{doc.source_file}: produced zero chunks"

    def test_chunk_text_not_empty(self, parsed_docs):
        for doc in parsed_docs:
            meta = extract_metadata(doc.markdown, doc.furniture_text, doc.source_file, doc.pdf_metadata)
            chunks = chunk_document(doc.markdown, meta)
            for i, chunk in enumerate(chunks):
                assert len(chunk.text.strip()) > 10, (
                    f"{doc.source_file} chunk {i}: text is too short"
                )

    def test_chunk_metadata_attached(self, parsed_docs):
        """Every chunk should carry the document's metadata."""
        for doc in parsed_docs:
            meta = extract_metadata(doc.markdown, doc.furniture_text, doc.source_file, doc.pdf_metadata)
            chunks = chunk_document(doc.markdown, meta)
            for chunk in chunks:
                assert chunk.metadata.aktenzeichen == meta.aktenzeichen
                assert chunk.metadata.source_file == meta.source_file

    def test_chunk_indices_sequential(self, parsed_docs):
        for doc in parsed_docs:
            meta = extract_metadata(doc.markdown, doc.furniture_text, doc.source_file, doc.pdf_metadata)
            chunks = chunk_document(doc.markdown, meta)
            indices = [c.chunk_index for c in chunks]
            assert indices == list(range(len(chunks))), (
                f"{doc.source_file}: chunk indices not sequential: {indices}"
            )


# ── Test: URL extraction ───────────────────────────────────────────


class TestUrlExtractionRealDocs:
    """External URLs are extracted for UC#6. Bundestag-internal links should be filtered out."""

    def test_no_bundestag_urls(self, parsed_docs):
        """Extracted URLs must not include bundestag.de internal links."""
        excluded = {"bundestag.de", "dserver.bundestag.de", "dip.bundestag.de", "www.bundestag.de"}
        for doc in parsed_docs:
            urls = extract_urls(doc.markdown)
            for u in urls:
                domain = re.match(r"https?://([^/:]+)", u.url)
                if domain:
                    assert domain.group(1).lower() not in excluded, (
                        f"{doc.source_file}: internal URL '{u.url}' was not filtered"
                    )

    def test_urls_are_valid(self, parsed_docs):
        for doc in parsed_docs:
            urls = extract_urls(doc.markdown)
            for u in urls:
                assert u.url.startswith("http://") or u.url.startswith("https://"), (
                    f"{doc.source_file}: invalid URL '{u.url}'"
                )

    def test_urls_have_real_domain(self, parsed_docs):
        """Every extracted URL must have a domain with at least one dot.

        This catches the truncation bug where the regex used to stop at the
        first '.' and produce 'https://www' instead of 'https://www.example.com'.
        """
        domain_re = re.compile(r"^https?://([^/:]+)")
        for doc in parsed_docs:
            urls = extract_urls(doc.markdown)
            for u in urls:
                m = domain_re.match(u.url)
                assert m, f"{doc.source_file}: cannot extract domain from '{u.url}'"
                domain = m.group(1)
                assert "." in domain, (
                    f"{doc.source_file}: URL truncated at first dot: '{u.url}'"
                )

    def test_urls_have_no_docling_escapes(self, parsed_docs):
        r"""URLs should not contain Docling markdown artifacts like \_ ."""
        for doc in parsed_docs:
            urls = extract_urls(doc.markdown)
            for u in urls:
                assert "\\_" not in u.url, (
                    f"{doc.source_file}: escaped underscore in URL: '{u.url}'"
                )
                assert "&amp;" not in u.url, (
                    f"{doc.source_file}: HTML entity in URL: '{u.url}'"
                )
