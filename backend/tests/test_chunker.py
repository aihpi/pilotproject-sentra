"""Chunking, and the provenance each chunk carries.

Rewritten against blocks rather than deleted. What these tests encode is the
*strategy* — split at headings, keep short documents whole, split an oversized
section at paragraph boundaries — and the strategy is not what changed. What
changed is that a heading is a `section_header` block rather than a `#` in a
string, and a paragraph boundary is the edge of a block rather than a blank
line, which is the same boundary described by the parser instead of inferred
from whitespace.

The provenance tests are new, and are why any of this happened: technique 4.3a
asks whether a cited passage supports the claim, and somebody has to be able to
find the passage.
"""

from sentra.domain import DocumentMetadata
from sentra.ingestion.chunker import chunk_document, is_boilerplate
from sentra.ingestion.parser import TextBlock, number_paragraphs


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


def _blocks(*items: tuple[str, str, int]) -> list[TextBlock]:
    """Blocks as the parser produces them, numbered the same way."""
    return number_paragraphs(items)


def _body(text: str, page: int = 1) -> tuple[str, str, int]:
    return (text, "text", page)


def _heading(text: str, page: int = 1) -> tuple[str, str, int]:
    return (text, "section_header", page)


# Long enough that a single section clears the short-document threshold, which
# is 1000 characters — below that a paper is one idea, and splitting it only
# separates a question from its answer. A section of one paragraph is a real
# shape, so the fixture has to be a realistic length rather than a token one.
LONG = "Ein Satz über die Rechtslage, lang genug um als Inhalt zu zählen. " * 20


class TestBoilerplate:
    def test_the_disclaimer_is_recognised(self):
        assert is_boilerplate(
            "Die Wissenschaftlichen Dienste des Deutschen Bundestages unterstützen die "
            "Mitglieder des Deutschen Bundestages bei ihrer mandatsbezogenen Tätigkeit."
        )

    def test_and_the_copyright_line(self):
        assert is_boilerplate("© 2023 Deutscher Bundestag")

    def test_and_an_image_placeholder(self):
        assert is_boilerplate("<!-- image -->")

    def test_ordinary_content_is_not(self):
        assert not is_boilerplate("Nach § 35 GOBT beträgt die Redezeit 15 Minuten.")

    def test_it_is_dropped_from_the_chunks(self):
        blocks = _blocks(
            _heading("1. Rechtslage"),
            _body("© 2023 Deutscher Bundestag"),
            _body(LONG),
        )

        chunks = chunk_document(blocks, _make_metadata())

        assert "Deutscher Bundestag" not in chunks[0].text

    def test_but_not_before_the_paragraphs_are_numbered(self):
        """The rule that keeps citations honest. A reviewer counting down the
        page counts the disclaimer too, because it is printed there — so the
        paragraph after it is the third on the page, not the second."""
        blocks = _blocks(
            _body("Erster Absatz."),
            _body("© 2023 Deutscher Bundestag"),
            _body(LONG),
        )

        chunks = chunk_document(blocks, _make_metadata(document_type="Kurzinformation"))

        assert chunks[0].paragraph_to == 3


class TestSections:
    def test_a_heading_starts_one(self):
        blocks = _blocks(_heading("1. Erstes"), _body(LONG), _heading("2. Zweites"), _body(LONG))

        chunks = chunk_document(blocks, _make_metadata())

        assert [c.section_title for c in chunks] == ["1. Erstes", "2. Zweites"]

    def test_content_before_the_first_heading_is_an_Einleitung(self):
        blocks = _blocks(_body(LONG), _heading("1. Erstes"), _body(LONG))

        chunks = chunk_document(blocks, _make_metadata())

        assert chunks[0].section_title == "Einleitung"

    def test_a_short_preamble_is_not_worth_a_section(self):
        blocks = _blocks(_body("Kurz."), _heading("1. Erstes"), _body(LONG))

        chunks = chunk_document(blocks, _make_metadata())

        assert [c.section_title for c in chunks] == ["1. Erstes"]

    def test_the_table_of_contents_is_skipped(self):
        """Navigation. Retrieving it answers nothing."""
        blocks = _blocks(
            _heading("Inhaltsverzeichnis"),
            _body("1. Erstes … 3"),
            _heading("1. Erstes"),
            _body(LONG),
        )

        chunks = chunk_document(blocks, _make_metadata())

        assert [c.section_title for c in chunks] == ["1. Erstes"]

    def test_the_section_number_is_kept_separately(self):
        blocks = _blocks(_heading("2.1. Rechtliche Grundlagen"), _body(LONG))

        chunks = chunk_document(blocks, _make_metadata())

        assert chunks[0].section_path == "2.1"

    def test_the_heading_stays_in_the_text(self):
        """Context for the answer: a passage that begins mid-argument reads
        differently without the heading it sat under."""
        blocks = _blocks(_heading("1. Rechtslage"), _body(LONG))

        chunks = chunk_document(blocks, _make_metadata())

        assert chunks[0].text.startswith("1. Rechtslage")

    def test_a_tiny_section_is_dropped(self):
        blocks = _blocks(_heading("1. Erstes"), _body("Kurz."), _heading("2. Zweites"), _body(LONG))

        chunks = chunk_document(blocks, _make_metadata())

        assert [c.section_title for c in chunks] == ["2. Zweites"]


class TestWholeDocuments:
    def test_a_Kurzinformation_stays_in_one_piece(self):
        blocks = _blocks(_heading("A"), _body(LONG), _heading("B"), _body(LONG))

        chunks = chunk_document(blocks, _make_metadata(document_type="Kurzinformation"))

        assert len(chunks) == 1

    def test_so_does_anything_short(self):
        blocks = _blocks(_heading("A"), _body("Kurzer Inhalt, aber lang genug."))

        chunks = chunk_document(blocks, _make_metadata())

        assert len(chunks) == 1

    def test_nothing_in_means_nothing_out(self):
        assert chunk_document([], _make_metadata()) == []

    def test_a_document_of_pure_boilerplate_produces_nothing(self):
        blocks = _blocks(_body("© 2023 Deutscher Bundestag"))

        assert chunk_document(blocks, _make_metadata()) == []


class TestOversizedSections:
    def test_a_long_section_is_split_at_block_boundaries(self):
        blocks = _blocks(_heading("1. Lang"), *[_body(LONG) for _ in range(40)])

        chunks = chunk_document(blocks, _make_metadata(), max_tokens=100)

        assert len(chunks) > 1

    def test_and_the_parts_are_named(self):
        blocks = _blocks(_heading("1. Lang"), *[_body(LONG) for _ in range(40)])

        chunks = chunk_document(blocks, _make_metadata(), max_tokens=100)

        assert chunks[0].section_title == "1. Lang (Teil 1)"

    def test_a_section_that_fits_is_left_whole(self):
        blocks = _blocks(_heading("1. Kurz"), _body(LONG))

        chunks = chunk_document(blocks, _make_metadata(), max_tokens=2048)

        assert chunks[0].section_title == "1. Kurz"


class TestBookkeeping:
    def test_chunk_indices_run_in_order(self):
        blocks = _blocks(
            _heading("1. A"),
            _body(LONG),
            _heading("2. B"),
            _body(LONG),
            _heading("3. C"),
            _body(LONG),
        )

        chunks = chunk_document(blocks, _make_metadata())

        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))

    def test_the_metadata_rides_along(self):
        blocks = _blocks(_heading("1. A"), _body(LONG))

        chunks = chunk_document(blocks, _make_metadata())

        assert chunks[0].metadata.aktenzeichen == "WD 3 - 3000 - 029/23"


class TestProvenance:
    """Why any of this happened. 4.3a asks whether the cited passage supports
    the claim, and somebody has to be able to find the passage."""

    def test_a_chunk_knows_its_page(self):
        blocks = _blocks(_heading("1. A", 4), _body(LONG, 4))

        chunks = chunk_document(blocks, _make_metadata())

        assert (chunks[0].page_from, chunks[0].page_to) == (4, 4)

    def test_and_its_paragraphs_on_that_page(self):
        blocks = _blocks(_heading("1. A", 4), _body(LONG, 4), _body(LONG, 4))

        chunks = chunk_document(blocks, _make_metadata())

        assert (chunks[0].paragraph_from, chunks[0].paragraph_to) == (1, 2)

    def test_a_chunk_spanning_a_page_break_reports_both_ends(self):
        """ "S. 4, Abs. 2 bis S. 5, Abs. 1" — and the paragraph numbers belong
        to their own pages, because the count restarts on each."""
        blocks = _blocks(_heading("1. A", 4), _body(LONG, 4), _body(LONG, 4), _body(LONG, 5))

        chunks = chunk_document(blocks, _make_metadata())

        assert (chunks[0].page_from, chunks[0].paragraph_from) == (4, 1)
        assert (chunks[0].page_to, chunks[0].paragraph_to) == (5, 1)

    def test_a_footnote_does_not_take_a_paragraph_number(self):
        blocks = _blocks(
            _heading("1. A", 2),
            _body("Erster Absatz mit Inhalt, lang genug zum Behalten.", 2),
            ("1 Vgl. BVerfGE 123, 267.", "footnote", 2),
            _body(LONG, 2),
        )

        chunks = chunk_document(blocks, _make_metadata())

        assert chunks[0].paragraph_to == 2

    def test_a_heading_only_section_is_not_indexed(self):
        """It has nothing to answer from, and it would be cited as a passage at
        paragraph zero of its page — which is how a chunk containing no
        paragraph announces itself. Real shape: a numbered heading followed
        straight by its sub-headings."""
        blocks = _blocks(
            _heading("2. Situation in einzelnen EU-Mitgliedstaaten", 4),
            _heading("2.1. Belgien", 4),
            _body(LONG, 4),
        )

        chunks = chunk_document(blocks, _make_metadata())

        assert [c.section_title for c in chunks] == ["2.1. Belgien"]

    def test_every_chunk_can_be_cited(self):
        """The property the whole change exists for: no chunk reaches the index
        without somewhere a reviewer can look."""
        blocks = _blocks(_heading("1. A", 1), _body(LONG, 1), _heading("2. B", 2), _body(LONG, 2))

        chunks = chunk_document(blocks, _make_metadata())

        assert chunks
        assert all(c.page_from > 0 and c.paragraph_from > 0 for c in chunks)

    def test_each_chunk_of_a_split_section_carries_its_own_pages(self):
        blocks = _blocks(_heading("1. Lang", 1), *[_body(LONG, 1 + i // 10) for i in range(40)])

        chunks = chunk_document(blocks, _make_metadata(), max_tokens=100)

        assert chunks[0].page_from <= chunks[-1].page_from
        assert all(c.page_from > 0 for c in chunks)
