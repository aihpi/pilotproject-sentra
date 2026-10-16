"""Only the sources an answer cites (#268).

The number in [n] is the document's order of first appearance in the retrieved
passages. The context now writes that number into every passage header, and
the answer returns only the sources whose number appears in its text, each
keeping its number so the cards line up with the markers.

No LLM, no Qdrant: the store, the embedder and the generation are stubbed.
"""

from sentra.domain import Generation
from sentra.rag.generator import cited_numbers, format_context, source_numbers
from sentra.services.explorer import answer_question
from tests.test_explorer_helpers import AZ_A, AZ_B, hit

AZ_C = "WD 4 - 3000 - 115/22"

# A appears first, then B, then A again, then C: numbers 1, 2, 3.
HITS = [hit(AZ_A, 0.9), hit(AZ_B, 0.8), hit(AZ_A, 0.7), hit(AZ_C, 0.6)]


class _Store:
    def search(self, **kwargs):
        return HITS


class _Embedder:
    def embed_query(self, query):
        return [0.0]


class _Generator:
    def __init__(self, text):
        self.text = text
        self.context = ""

    def generate_answer(self, query, context, system_prompt=None):
        self.context = context
        return Generation(text=self.text)


def _answer(text):
    generator = _Generator(text)
    result = answer_question(
        query="Frage?",
        date_from=None,
        date_to=None,
        top_k=10,
        store=_Store(),
        embedder=_Embedder(),
        generator=generator,
    )
    return result, generator


class TestNumbering:
    def test_order_of_first_appearance(self):
        assert source_numbers(HITS) == {AZ_A: 1, AZ_B: 2, AZ_C: 3}

    def test_the_model_reads_the_number_in_every_header(self):
        """A second passage from the same paper carries the same number, which
        is the counting the model used to have to do itself."""
        out = format_context(HITS)

        assert out.count(f"[Quelle 1: {AZ_A}") == 2
        assert f"[Quelle 2: {AZ_B}" in out
        assert f"[Quelle 3: {AZ_C}" in out


class TestReadingMarkers:
    def test_single_and_bold_markers(self):
        assert cited_numbers("Laut **[1]** und [3] gilt das.") == {1, 3}

    def test_lists_inside_one_bracket(self):
        assert cited_numbers("Siehe [1, 3] sowie [2;4].") == {1, 2, 3, 4}

    def test_no_markers(self):
        assert cited_numbers("Dazu liegen keine Informationen vor.") == set()

    def test_a_header_echoed_back_is_not_a_marker(self):
        assert cited_numbers("[Quelle 2: WD 9 - 3000 - 068/23]") == set()


class TestTheReturnedSources:
    def test_only_the_cited_ones_with_their_numbers(self):
        result, _ = _answer("Das folgt aus [1] und [3].")

        assert [(s.aktenzeichen, s.nummer) for s in result.sources] == [(AZ_A, 1), (AZ_C, 3)]

    def test_an_answer_without_markers_lists_no_sources(self):
        result, _ = _answer("Dazu enthält der Bestand keine Informationen.")

        assert result.sources == []

    def test_a_marker_past_the_retrieved_sources_is_ignored(self):
        """The harness reports it as a dangling marker; here it just matches nothing."""
        result, _ = _answer("Siehe [2] und [7].")

        assert [s.nummer for s in result.sources] == [2]

    def test_the_context_the_model_saw_is_numbered(self):
        _, generator = _answer("[1]")

        assert f"[Quelle 1: {AZ_A}" in generator.context
