"""Tests for query service source deduplication and preview logic."""

from sentra.services.query import Source, _build_sources


def _make_result(
    aktenzeichen="WD 3 - 3000 - 029/23",
    title="Test Doc",
    section_title="Section 1",
    fachbereich="Verfassung und Verwaltung",
    score=0.85,
    text="Some chunk text here.",
    source_file="test.pdf",
) -> dict:
    return dict(
        aktenzeichen=aktenzeichen,
        title=title,
        section_title=section_title,
        fachbereich=fachbereich,
        score=score,
        text=text,
        source_file=source_file,
    )


class TestBuildSources:
    def test_basic(self):
        results = [_make_result()]
        sources = _build_sources(results)
        assert len(sources) == 1
        assert sources[0].aktenzeichen == "WD 3 - 3000 - 029/23"
        assert sources[0].score == 0.85

    def test_deduplicates_same_az_and_section(self):
        results = [
            _make_result(score=0.9),
            _make_result(score=0.8),  # same az + section
        ]
        sources = _build_sources(results)
        assert len(sources) == 1
        assert sources[0].score == 0.9  # keeps first

    def test_different_sections_not_deduped(self):
        results = [
            _make_result(section_title="Section 1"),
            _make_result(section_title="Section 2"),
        ]
        sources = _build_sources(results)
        assert len(sources) == 2

    def test_different_documents_not_deduped(self):
        results = [
            _make_result(aktenzeichen="WD 3 - 3000 - 029/23"),
            _make_result(aktenzeichen="WD 6 - 3000 - 052/24"),
        ]
        sources = _build_sources(results)
        assert len(sources) == 2

    def test_preview_truncated_at_200(self):
        long_text = "A" * 300
        results = [_make_result(text=long_text)]
        sources = _build_sources(results)
        assert sources[0].text_preview.endswith("...")
        assert len(sources[0].text_preview) == 203  # 200 + "..."

    def test_preview_strips_section_title_prefix(self):
        results = [_make_result(section_title="My Section", text="My Section\n\nActual content.")]
        sources = _build_sources(results)
        assert sources[0].text_preview == "Actual content."

    def test_empty_results(self):
        assert _build_sources([]) == []
