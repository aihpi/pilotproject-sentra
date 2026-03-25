"""Tests for document chunking logic."""

import pytest

from sentra.ingestion.chunker import (
    Chunk,
    _split_into_sections,
    _split_on_paragraphs,
    _strip_boilerplate,
    chunk_document,
)
from sentra.ingestion.metadata import DocumentMetadata


def _make_metadata(**overrides) -> DocumentMetadata:
    defaults = dict(
        aktenzeichen="WD 3 - 3000 - 029/23",
        fachbereich_number="WD 3",
        fachbereich="Verfassung und Verwaltung",
        document_type="Ausarbeitung",
        title="Test Document",
        completion_date="2025-01-01",
        language="de",
        source_file="test.pdf",
    )
    defaults.update(overrides)
    return DocumentMetadata(**defaults)


# ---------------------------------------------------------------------------
# Boilerplate stripping
# ---------------------------------------------------------------------------


class TestStripBoilerplate:
    def test_removes_end_marker(self):
        text = "Some content\n\n***"
        assert "***" not in _strip_boilerplate(text)

    def test_removes_copyright(self):
        text = "Content\n© 2024 Deutscher Bundestag"
        assert "©" not in _strip_boilerplate(text)

    def test_removes_image_placeholders(self):
        text = "Before <!-- image --> After"
        assert "<!-- image -->" not in _strip_boilerplate(text)
        assert "Before" in _strip_boilerplate(text)
        assert "After" in _strip_boilerplate(text)

    def test_removes_repeated_wd_header(self):
        text = "## Wissenschaftliche Dienste  Wissenschaftliche Dienste\nContent"
        result = _strip_boilerplate(text)
        assert "Wissenschaftliche Dienste  Wissenschaftliche Dienste" not in result

    def test_removes_bundestag_heading(self):
        text = "## Deutscher Bundestag\nContent here"
        result = _strip_boilerplate(text)
        assert "Deutscher Bundestag" not in result

    def test_collapses_blank_lines(self):
        text = "A\n\n\n\n\nB"
        assert _strip_boilerplate(text) == "A\n\nB"

    def test_preserves_normal_content(self):
        text = "## Section Title\n\nNormal paragraph content."
        assert _strip_boilerplate(text) == text


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------


class TestSplitIntoSections:
    def test_splits_on_headers(self):
        md = "## Section A\nContent A\n## Section B\nContent B"
        sections = _split_into_sections(md)
        assert len(sections) == 2
        assert sections[0][0] == "Section A"
        assert sections[1][0] == "Section B"

    def test_preamble_included(self):
        md = (
            "This is a long preamble that should be captured as an introduction "
            "section.\n\n## First Section\nContent"
        )
        sections = _split_into_sections(md)
        assert sections[0][0] == "Einleitung"
        assert "preamble" in sections[0][2]

    def test_short_preamble_skipped(self):
        md = "Short\n## Section\nContent"
        sections = _split_into_sections(md)
        assert sections[0][0] == "Section"

    def test_no_headers_returns_whole_doc(self):
        md = "Just text without any headers at all."
        sections = _split_into_sections(md)
        assert len(sections) == 1
        assert sections[0][0] == "Inhalt"

    def test_skips_toc_heading(self):
        md = "## Inhaltsverzeichnis\n1. Foo\n## Real Section\nContent"
        sections = _split_into_sections(md)
        titles = [s[0] for s in sections]
        assert "Inhaltsverzeichnis" not in titles
        assert "Real Section" in titles

    def test_section_number_extraction(self):
        md = "## 2.1. Rechtliche Grundlagen\nContent"
        sections = _split_into_sections(md)
        assert sections[0][1] == "2.1"  # section_path


# ---------------------------------------------------------------------------
# Paragraph splitting for oversized sections
# ---------------------------------------------------------------------------


class TestSplitOnParagraphs:
    def test_fits_in_one(self):
        text = "Short paragraph."
        assert _split_on_paragraphs(text, max_tokens=100) == ["Short paragraph."]

    def test_splits_at_paragraph_boundary(self):
        # Each 'x' * 400 = 100 tokens. max_tokens=150 should split into two.
        p1 = "x" * 400
        p2 = "y" * 400
        text = f"{p1}\n\n{p2}"
        chunks = _split_on_paragraphs(text, max_tokens=150)
        assert len(chunks) == 2
        assert chunks[0] == p1
        assert chunks[1] == p2

    def test_groups_small_paragraphs(self):
        text = "A\n\nB\n\nC"
        chunks = _split_on_paragraphs(text, max_tokens=1000)
        assert len(chunks) == 1
        assert chunks[0] == "A\n\nB\n\nC"


# ---------------------------------------------------------------------------
# Full chunk_document
# ---------------------------------------------------------------------------


class TestChunkDocument:
    def test_kurzinformation_single_chunk(self):
        md = "Short content about a topic."
        meta = _make_metadata(document_type="Kurzinformation")
        chunks = chunk_document(md, meta)
        assert len(chunks) == 1
        assert chunks[0].section_title == meta.title
        assert chunks[0].chunk_index == 0

    def test_short_doc_single_chunk(self):
        md = "Very short." * 10  # < 1000 chars
        meta = _make_metadata(document_type="Ausarbeitung")
        chunks = chunk_document(md, meta)
        assert len(chunks) == 1

    def test_sectioned_doc_multiple_chunks(self):
        sections = []
        for i in range(3):
            sections.append(f"## Section {i}\n\n{'Content paragraph. ' * 20}")
        md = "\n\n".join(sections)
        meta = _make_metadata()
        chunks = chunk_document(md, meta)
        assert len(chunks) == 3
        assert chunks[0].section_title == "Section 0"
        assert chunks[2].chunk_index == 2

    def test_empty_doc_returns_nothing(self):
        meta = _make_metadata(document_type="Kurzinformation")
        assert chunk_document("", meta) == []
        assert chunk_document("   \n\n  ", meta) == []

    def test_skips_tiny_sections(self):
        # Content must exceed 1000 chars to avoid the short-doc single-chunk path
        md = "## Good Section\n\n" + ("Content word. " * 80) + "\n\n## Tiny\nHi"
        meta = _make_metadata()
        chunks = chunk_document(md, meta)
        titles = [c.section_title for c in chunks]
        assert "Good Section" in titles
        assert "Tiny" not in titles  # < 30 chars, skipped

    def test_oversized_section_splits(self):
        # Create a section > max_tokens (using max_tokens=50 for the test)
        big_section = "## Big Section\n\n" + "\n\n".join(
            [f"Paragraph {i}. " + "word " * 60 for i in range(5)]
        )
        meta = _make_metadata()
        chunks = chunk_document(big_section, meta, max_tokens=50)
        assert len(chunks) > 1
        assert "Teil" in chunks[0].section_title or "Teil" in chunks[1].section_title

    def test_chunk_indices_sequential(self):
        md = "\n\n".join(
            [f"## Section {i}\n\n{'Text. ' * 20}" for i in range(4)]
        )
        meta = _make_metadata()
        chunks = chunk_document(md, meta)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_metadata_attached_to_chunks(self):
        md = "## Test\n\n" + "Content. " * 20
        meta = _make_metadata(aktenzeichen="WD 9 - 3000 - 100/21")
        chunks = chunk_document(md, meta)
        assert all(c.metadata.aktenzeichen == "WD 9 - 3000 - 100/21" for c in chunks)
