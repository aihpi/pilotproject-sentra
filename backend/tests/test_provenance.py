"""Page and paragraph, carried out of the parser instead of thrown away.

`parse_pdfs` called `export_to_markdown()` and the export drops provenance,
which is the single reason technique 4.3a could not be implemented: the model
cannot cite finer than a section because it is never told anything finer.

The numbering rule is tested here without Docling, deliberately. Docling is 5
to 20 seconds a document, so anything needing it is an integration test and
effectively untested in CI — while the decisions all live in the rule. What
counts as a paragraph, and where the count restarts, are the things that will
be wrong if anything is.
"""

import pytest

from sentra.ingestion.parser import BODY_LABELS, TextBlock, number_paragraphs


def _numbered(*items: tuple[str, str, int]) -> list[TextBlock]:
    return number_paragraphs(items)


class TestNumberingParagraphs:
    def test_body_text_counts_from_one(self):
        blocks = _numbered(("erster", "text", 1), ("zweiter", "text", 1))

        assert [b.paragraph for b in blocks] == [1, 2]

    def test_the_count_restarts_on_each_page(self):
        """Per page, because "page 4, third paragraph" is what a reviewer
        holding the PDF can verify by counting."""
        blocks = _numbered(("a", "text", 1), ("b", "text", 1), ("c", "text", 2), ("d", "text", 2))

        assert [(b.page, b.paragraph) for b in blocks] == [(1, 1), (1, 2), (2, 1), (2, 2)]

    def test_a_list_item_is_body_text(self):
        blocks = _numbered(("intro", "text", 1), ("erstens", "list_item", 1))

        assert [b.paragraph for b in blocks] == [1, 2]


class TestWhatIsNotAParagraph:
    def test_a_heading_keeps_its_page_but_is_not_counted(self):
        blocks = _numbered(("2.1 Rechtslage", "section_header", 3), ("Dazu gilt", "text", 3))

        assert blocks[0].paragraph is None
        assert blocks[0].page == 3
        assert blocks[1].paragraph == 1

    def test_a_footnote_does_not_shift_the_numbering(self):
        """The one that matters. Counting apparatus as body text would shift
        paragraph numbers on exactly the pages that carry the most citations —
        which are the pages a 4.3a check is most likely to be about."""
        blocks = _numbered(
            ("erster Absatz", "text", 4),
            ("1 Vgl. BVerfGE 123, 267.", "footnote", 4),
            ("zweiter Absatz", "text", 4),
        )

        assert [b.paragraph for b in blocks] == [1, None, 2]

    def test_a_caption_likewise(self):
        blocks = _numbered(("Abbildung 1: Ablauf", "caption", 2), ("Text dazu", "text", 2))

        assert [b.paragraph for b in blocks] == [None, 1]

    def test_the_body_labels_are_stated_rather_than_implied(self):
        """A judgement worth being able to find. If this set changes, every
        paragraph number in the corpus changes with it."""
        assert frozenset({"text", "list_item"}) == BODY_LABELS


class TestEdges:
    def test_no_items_is_no_blocks(self):
        assert number_paragraphs([]) == []

    def test_a_page_of_nothing_but_apparatus_numbers_nothing(self):
        blocks = _numbered(("Abb. 1", "caption", 7), ("1 Ebd.", "footnote", 7))

        assert all(b.paragraph is None for b in blocks)

    def test_pages_need_not_be_consecutive(self):
        """Docling reports the page an item is on, and a document can have
        items this walk skipped — one with no provenance, for instance."""
        blocks = _numbered(("a", "text", 1), ("b", "text", 5))

        assert [(b.page, b.paragraph) for b in blocks] == [(1, 1), (5, 1)]

    def test_returning_to_an_earlier_page_restarts_it_again(self):
        """Not a real reading order, but the rule should be "the page
        changed", not "the page increased" — a footnote block placed after a
        page break would otherwise carry a number from the wrong page."""
        blocks = _numbered(("a", "text", 2), ("b", "text", 3), ("c", "text", 2))

        assert [b.paragraph for b in blocks] == [1, 1, 1]


@pytest.mark.integration
class TestAgainstARealDocument:
    def test_every_block_of_a_real_paper_has_a_page(self, tmp_path):
        """In principle Docling records provenance; this says it does for this
        corpus, which is the claim #134 rests on.

        Integration because it runs Docling — 5 to 20 seconds for one file.
        """
        from pathlib import Path

        from sentra.ingestion.parser import parse_pdfs

        corpus = Path(__file__).parent / "fixtures" / "corpus"
        one = sorted(corpus.glob("*.pdf"))[0]

        parsed = next(iter(parse_pdfs(str(corpus), pdf_paths=[one])))

        assert parsed.blocks, "no blocks came out of a real document"
        assert all(b.page >= 1 for b in parsed.blocks)
        assert any(b.paragraph == 1 for b in parsed.blocks)
        # The markdown path still works: metadata extraction depends on it.
        assert parsed.markdown
