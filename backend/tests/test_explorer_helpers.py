"""Unit tests for the aggregation and source-reference helpers.

These ran only under the integration tier before, which meant they needed
Qdrant and the AI Hub and were skipped on every ordinary test run. Now that the
store returns typed hits, the helpers can be driven with hits built by hand, so
these are offline.

The ordering test matters more than it looks: the prompts tell the model that
[1], [2] and so on refer to the sources in order of first appearance, and
_build_source_refs is what produces that order. Nothing checked it until now.

Run:  uv run pytest tests/test_explorer_helpers.py -v
"""

from sentra.domain import Hit
from sentra.rag.generator import format_context
from sentra.services.explorer import _aggregate_docs, _build_source_refs


def hit(
    az: str,
    score: float,
    *,
    title: str = "",
    section: str = "",
    text: str = "",
    page_from: int = 0,
    page_to: int = 0,
    paragraph_from: int = 0,
    paragraph_to: int = 0,
) -> Hit:
    """A Hit with only the fields a test cares about set.

    The location defaults to zero, which is what a chunk written before #134
    carries — so a test that says nothing about pages is testing the case the
    index is still full of.
    """
    return Hit(
        score=score,
        text=text,
        section_title=section,
        section_path="",
        page_from=page_from,
        page_to=page_to,
        paragraph_from=paragraph_from,
        paragraph_to=paragraph_to,
        chunk_index=0,
        aktenzeichen=az,
        fachbereich_number=az.split(" - ")[0],
        fachbereich="Fachbereich",
        document_type="Ausarbeitung",
        title=title or f"Titel {az}",
        completion_date="2024-01-01",
        language="de",
        source_file=f"{az}.pdf",
    )


AZ_A = "WD 3 - 3000 - 029/23"
AZ_B = "WD 9 - 3000 - 068/23"
AZ_C = "EU 6 - 3000 - 012/25"


class TestAggregateDocs:
    def test_empty_input(self):
        assert _aggregate_docs([], top_k=10) == []

    def test_one_row_per_document(self):
        hits = [hit(AZ_A, 0.9), hit(AZ_A, 0.8), hit(AZ_B, 0.7)]
        docs = _aggregate_docs(hits, top_k=10)
        assert [d.aktenzeichen for d in docs] == [AZ_A, AZ_B]

    def test_best_chunk_wins(self):
        """A document is scored by its strongest chunk, not its first or last."""
        hits = [hit(AZ_A, 0.4), hit(AZ_A, 0.91), hit(AZ_A, 0.5)]
        assert _aggregate_docs(hits, top_k=10)[0].relevance_score == 0.91

    def test_sorted_by_descending_score(self):
        hits = [hit(AZ_A, 0.3), hit(AZ_B, 0.9), hit(AZ_C, 0.6)]
        docs = _aggregate_docs(hits, top_k=10)
        assert [d.aktenzeichen for d in docs] == [AZ_B, AZ_C, AZ_A]
        assert [d.relevance_score for d in docs] == sorted(
            (d.relevance_score for d in docs), reverse=True
        )

    def test_top_k_applies_after_aggregation(self):
        """top_k limits documents, not chunks, so duplicates must not consume it."""
        hits = [hit(AZ_A, 0.9), hit(AZ_A, 0.8), hit(AZ_B, 0.7), hit(AZ_C, 0.6)]
        docs = _aggregate_docs(hits, top_k=2)
        assert [d.aktenzeichen for d in docs] == [AZ_A, AZ_B]

    def test_score_is_rounded(self):
        assert _aggregate_docs([hit(AZ_A, 0.123456789)], top_k=1)[0].relevance_score == 0.1235

    def test_document_fields_carried_through(self):
        doc = _aggregate_docs([hit(AZ_A, 0.5, title="Ein Titel")], top_k=1)[0]
        assert doc.title == "Ein Titel"
        assert doc.document_type == "Ausarbeitung"
        assert doc.completion_date == "2024-01-01"
        assert doc.source_file == f"{AZ_A}.pdf"


class TestBuildSourceRefs:
    def test_empty_input(self):
        assert _build_source_refs([]) == []

    def test_deduplicates_by_aktenzeichen(self):
        refs = _build_source_refs([hit(AZ_A, 0.9), hit(AZ_A, 0.8), hit(AZ_A, 0.1)])
        assert len(refs) == 1

    def test_order_is_first_appearance_not_score(self):
        """This is the order the [n] markers in a generated answer refer to."""
        hits = [hit(AZ_B, 0.2), hit(AZ_A, 0.9), hit(AZ_C, 0.5)]
        assert [r.aktenzeichen for r in _build_source_refs(hits)] == [AZ_B, AZ_A, AZ_C]

    def test_a_later_duplicate_does_not_move_a_source_up(self):
        hits = [hit(AZ_A, 0.1), hit(AZ_B, 0.2), hit(AZ_A, 0.99)]
        assert [r.aktenzeichen for r in _build_source_refs(hits)] == [AZ_A, AZ_B]

    def test_fields_carried_through(self):
        ref = _build_source_refs([hit(AZ_A, 0.5, title="Ein Titel")])[0]
        assert ref.title == "Ein Titel"
        assert ref.fachbereich == "Fachbereich"
        assert ref.completion_date == "2024-01-01"
        assert ref.source_file == f"{AZ_A}.pdf"


class TestFormatContext:
    def test_empty_input(self):
        assert format_context([]) == ""

    def test_header_names_the_source_and_section(self):
        out = format_context([hit(AZ_A, 0.9, section="2.1 Grundlagen", text="Inhalt")])
        assert f"[Quelle: {AZ_A}, Abschnitt: 2.1 Grundlagen]" in out
        assert "Inhalt" in out

    def test_hits_are_separated(self):
        out = format_context([hit(AZ_A, 0.9, text="eins"), hit(AZ_B, 0.8, text="zwei")])
        assert out.count("[Quelle:") == 2
        assert "---" in out

    def test_a_chunk_with_no_page_gets_no_location(self):
        """This test used to assert that the context contained no page at all,
        and documented why: the model could not cite one because it was never
        shown one. Since #183 it is shown one — when there is one.

        A chunk written before provenance existed has no page recorded, and it
        must not acquire an invented one: a citation that looks checkable and
        is not is worse than a section reference that is honest about its
        precision. The index outlives a schema change, so this is the ordinary
        case until the corpus is re-ingested, not an edge.
        """
        out = format_context([hit(AZ_A, 0.9, section="2.1", text="Inhalt")])

        assert "Seite" not in out
        assert f"[Quelle: {AZ_A}, Abschnitt: 2.1]" in out

    def test_a_chunk_with_a_page_is_cited_with_it(self):
        out = format_context(
            [
                hit(
                    AZ_A,
                    0.9,
                    section="2.1",
                    text="Inhalt",
                    page_from=4,
                    page_to=4,
                    paragraph_from=3,
                    paragraph_to=3,
                )
            ]
        )

        assert "Seite 4, Absatz 3" in out

    def test_a_passage_crossing_a_page_break_names_both_ends(self):
        """The paragraph is given with its own page at each end, because the
        count restarts on every page — "Absatz 1" means nothing on its own."""
        out = format_context(
            [
                hit(
                    AZ_A,
                    0.9,
                    section="2.1",
                    text="Inhalt",
                    page_from=4,
                    page_to=5,
                    paragraph_from=5,
                    paragraph_to=1,
                )
            ]
        )

        assert "Seite 4, Absatz 5 bis Seite 5, Absatz 1" in out

    def test_the_location_is_german_like_the_prompt_around_it(self):
        """A model told "page" writes "page", and the answer is German."""
        out = format_context([hit(AZ_A, 0.9, text="Inhalt", page_from=2, page_to=2)])

        assert "page" not in out.lower()
        assert "Seite 2" in out
