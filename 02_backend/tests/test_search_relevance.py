"""Search relevance tests against real indexed data.

These tests verify the core user experience: "I search for X, and the
right document appears near the top."  Each test encodes a domain-knowledge
expectation that was established by reading the actual PDF contents.

Requires: Qdrant running + data ingested (mark: integration).
Run:  uv run pytest tests/test_search_relevance.py -v -m integration
"""

import pytest

from sentra.config import Settings
from sentra.services.explorer import search_documents_by_topic

pytestmark = pytest.mark.integration


# ── Helpers ─────────────────────────────────────────────────────────


def _search(query: str, settings: Settings, top_k: int = 10, **filters):
    """Shortcut: run a topic search and return DocumentSearchResult list."""
    return search_documents_by_topic(
        query=query,
        date_from=filters.get("date_from"),
        date_to=filters.get("date_to"),
        top_k=top_k,
        settings=settings,
        fachbereich=filters.get("fachbereich"),
        document_type=filters.get("document_type"),
    )


def _fachbereich_set(results) -> set[str]:
    """Derive fachbereich_number from the aktenzeichen prefix."""
    return {r.aktenzeichen.split(" - ")[0].strip() for r in results}


# ── Test: Topic queries return relevant documents ──────────────────


class TestTopicRelevance:
    """Each test asserts that a topically obvious query surfaces the expected document."""

    def test_visa_query_finds_wd3(self, require_qdrant, settings):
        """WD 3-029-23 is about visa exemptions (Ausnahmen von der Visumspflicht)."""
        results = _search("Visumspflicht Visum Aufenthaltserlaubnis", settings)
        assert len(results) > 0, "No results for visa query"
        fb_set = _fachbereich_set(results[:5])
        assert "WD 3" in fb_set, (
            f"Expected WD 3 doc in top 5 for visa query, got: "
            f"{[r.aktenzeichen for r in results[:5]]}"
        )

    def test_health_query_finds_wd9(self, require_qdrant, settings):
        """WD 9 handles Gesundheit, Familie, Senioren, Frauen und Jugend."""
        results = _search("Gesundheit Krankenversicherung Pflege", settings)
        assert len(results) > 0
        fb_set = _fachbereich_set(results[:5])
        assert "WD 9" in fb_set, (
            f"Expected WD 9 doc in top 5 for health query, got: "
            f"{[r.aktenzeichen for r in results[:5]]}"
        )

    def test_eu_query_finds_eu6(self, require_qdrant, settings):
        """EU 6 handles European affairs."""
        results = _search("Europäische Union EU-Recht", settings)
        assert len(results) > 0
        fb_set = _fachbereich_set(results[:5])
        assert "EU 6" in fb_set, (
            f"Expected EU 6 doc in top 5 for EU query, got: "
            f"{[r.aktenzeichen for r in results[:5]]}"
        )

    def test_environment_query_finds_wd8(self, require_qdrant, settings):
        """WD 8 handles Umwelt, Naturschutz, Reaktorsicherheit, Bildung und Forschung."""
        results = _search("Umweltschutz Klimaschutz Naturschutz", settings)
        assert len(results) > 0
        fb_set = _fachbereich_set(results[:5])
        assert "WD 8" in fb_set, (
            f"Expected WD 8 doc in top 5 for environment query, got: "
            f"{[r.aktenzeichen for r in results[:5]]}"
        )

    def test_labor_social_query_finds_wd6(self, require_qdrant, settings):
        """WD 6 handles Arbeit und Soziales."""
        results = _search("Arbeitsrecht Sozialversicherung Rente", settings)
        assert len(results) > 0
        fb_set = _fachbereich_set(results[:5])
        assert "WD 6" in fb_set, (
            f"Expected WD 6 doc in top 5 for labor/social query, got: "
            f"{[r.aktenzeichen for r in results[:5]]}"
        )

    def test_budget_finance_query_finds_wd4(self, require_qdrant, settings):
        """WD 4 handles Haushalt und Finanzen."""
        results = _search("Bundeshaushalt Steuern Finanzen", settings)
        assert len(results) > 0
        fb_set = _fachbereich_set(results[:5])
        assert "WD 4" in fb_set, (
            f"Expected WD 4 doc in top 5 for budget/finance query, got: "
            f"{[r.aktenzeichen for r in results[:5]]}"
        )


# ── Test: Result ordering ──────────────────────────────────────────


class TestResultOrdering:
    """Users scan results top-to-bottom. Results must be sorted by relevance."""

    def test_sorted_by_descending_relevance(self, require_qdrant, settings):
        results = _search("Gesetzgebung Bundestag", settings, top_k=17)
        assert len(results) >= 2, "Need at least 2 results to test ordering"
        scores = [r.relevance_score for r in results]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Results not sorted by relevance: position {i} has {scores[i]}, "
                f"position {i+1} has {scores[i+1]}"
            )

    def test_relevance_scores_in_valid_range(self, require_qdrant, settings):
        results = _search("Recht und Gesetz", settings, top_k=17)
        for r in results:
            assert 0.0 <= r.relevance_score <= 1.0, (
                f"{r.aktenzeichen}: score {r.relevance_score} outside [0, 1]"
            )

    def test_no_duplicate_documents(self, require_qdrant, settings):
        """Chunk aggregation should produce unique documents, not duplicates."""
        results = _search("Deutschland Politik Recht", settings, top_k=17)
        seen = set()
        for r in results:
            assert r.aktenzeichen not in seen, (
                f"Duplicate document in results: {r.aktenzeichen}"
            )
            seen.add(r.aktenzeichen)


# ── Test: Broad query returns multiple documents ───────────────────


class TestBroadQuery:
    """A broad query about German law/policy should surface documents from
    multiple Fachbereiche, not just one."""

    def test_broad_query_finds_multiple_fachbereiche(self, require_qdrant, settings):
        results = _search("Recht Gesetzgebung Deutschland Bundestag", settings, top_k=17)
        fb_set = _fachbereich_set(results)
        assert len(fb_set) >= 3, (
            f"Broad query should find docs from >= 3 Fachbereiche, got {len(fb_set)}: {fb_set}"
        )

    def test_high_topk_returns_all_docs(self, require_qdrant, settings):
        """With top_k=17 (total PDFs) and a broad query, we should get most documents."""
        results = _search("Wissenschaftliche Dienste Bundestag", settings, top_k=17)
        # With only 17 docs, a very broad query should return at least ~10
        assert len(results) >= 10, (
            f"Broad query with top_k=17 returned only {len(results)} results"
        )
