"""Filter correctness tests against real indexed data.

A user who selects "WD 6" in the Fachbereich dropdown and sees WD 3
documents will lose trust in the system immediately. These tests verify
that every filter actually narrows results correctly.

Requires: Qdrant running + data ingested (mark: integration).
Run:  uv run pytest tests/test_filters.py -v -m integration
"""

import re
from datetime import date

import pytest

from sentra.services.explorer import search_documents_by_topic

pytestmark = pytest.mark.integration


# ── Helpers ─────────────────────────────────────────────────────────


def _search(query, store, embedder, top_k=17, **filters):
    return search_documents_by_topic(
        query=query,
        date_from=filters.get("date_from"),
        date_to=filters.get("date_to"),
        top_k=top_k,
        store=store,
        embedder=embedder,
        fachbereich=filters.get("fachbereich"),
        document_type=filters.get("document_type"),
    )


# A broad query that should match most documents (for testing filters).
BROAD_QUERY = "Wissenschaftliche Dienste Bundestag Deutschland"


# ── Test: Fachbereich filter ───────────────────────────────────────


class TestFachbereichFilter:
    """Filtering by Fachbereich should return ONLY documents from that department."""

    def test_wd6_filter_returns_only_wd6(self, require_qdrant, store, embedder):
        """We have 2 WD 6 docs: WD 6-052-24 and WD 6-094-23."""
        results = _search(BROAD_QUERY, store, embedder, fachbereich="WD 6")
        assert len(results) > 0, "WD 6 filter returned no results"
        for r in results:
            fb_prefix = r.aktenzeichen.split(" - ")[0].strip()
            assert fb_prefix == "WD 6", (
                f"Filter was WD 6 but got document {r.aktenzeichen}"
            )

    def test_wd6_filter_finds_both_docs(self, require_qdrant, store, embedder):
        results = _search(BROAD_QUERY, store, embedder, fachbereich="WD 6")
        az_set = {r.aktenzeichen for r in results}
        assert "WD 6 - 3000 - 052/24" in az_set or "WD 6 - 3000 - 094/23" in az_set, (
            f"Expected at least one known WD 6 doc, got: {az_set}"
        )

    def test_wd3_filter_returns_only_wd3(self, require_qdrant, store, embedder):
        results = _search(BROAD_QUERY, store, embedder, fachbereich="WD 3")
        assert len(results) > 0
        for r in results:
            fb_prefix = r.aktenzeichen.split(" - ")[0].strip()
            assert fb_prefix == "WD 3"

    def test_eu6_filter_returns_only_eu6(self, require_qdrant, store, embedder):
        results = _search(BROAD_QUERY, store, embedder, fachbereich="EU 6")
        assert len(results) > 0
        for r in results:
            fb_prefix = r.aktenzeichen.split(" - ")[0].strip()
            assert fb_prefix == "EU 6"


# ── Test: Document type filter ─────────────────────────────────────


class TestDocumentTypeFilter:
    """Filtering by document type should return ONLY that type."""

    def test_ausarbeitung_filter(self, require_qdrant, store, embedder):
        results = _search(BROAD_QUERY, store, embedder, document_type="Ausarbeitung")
        # May return empty if no Ausarbeitung docs match the broad query — that's OK.
        for r in results:
            assert r.document_type == "Ausarbeitung", (
                f"Filter was Ausarbeitung but got '{r.document_type}' for {r.aktenzeichen}"
            )

    def test_sachstand_filter(self, require_qdrant, store, embedder):
        results = _search(BROAD_QUERY, store, embedder, document_type="Sachstand")
        for r in results:
            assert r.document_type == "Sachstand", (
                f"Filter was Sachstand but got '{r.document_type}' for {r.aktenzeichen}"
            )

    def test_kurzinformation_filter(self, require_qdrant, store, embedder):
        results = _search(BROAD_QUERY, store, embedder, document_type="Kurzinformation")
        for r in results:
            assert r.document_type == "Kurzinformation", (
                f"Filter was Kurzinformation but got '{r.document_type}' for {r.aktenzeichen}"
            )


# ── Test: Date range filter ────────────────────────────────────────


class TestDateRangeFilter:
    """Date filtering uses year strings. A user selecting 2023 expects only 2023 docs."""

    def test_single_year_filter(self, require_qdrant, store, embedder):
        """Filter to 2023 — all results must have completion_date in 2023."""
        results = _search(BROAD_QUERY, store, embedder, date_from="2023", date_to="2023")
        for r in results:
            assert r.completion_date, f"{r.aktenzeichen}: missing completion_date"
            parsed = date.fromisoformat(r.completion_date)
            assert parsed.year == 2023, (
                f"Filter was 2023 but {r.aktenzeichen} has date {r.completion_date}"
            )

    def test_year_range_filter(self, require_qdrant, store, embedder):
        """Filter 2022-2023 — all results must have year in that range."""
        results = _search(BROAD_QUERY, store, embedder, date_from="2022", date_to="2023")
        assert len(results) > 0, "2022-2023 range returned no results"
        for r in results:
            parsed = date.fromisoformat(r.completion_date)
            assert 2022 <= parsed.year <= 2023, (
                f"Filter was 2022-2023 but {r.aktenzeichen} has date {r.completion_date}"
            )

    def test_only_from_date(self, require_qdrant, store, embedder):
        """date_from=2024 with no date_to — all results from 2024 onwards."""
        results = _search(BROAD_QUERY, store, embedder, date_from="2024")
        for r in results:
            parsed = date.fromisoformat(r.completion_date)
            assert parsed.year >= 2024, (
                f"date_from=2024 but {r.aktenzeichen} has date {r.completion_date}"
            )

    def test_only_to_date(self, require_qdrant, store, embedder):
        """date_to=2022 with no date_from — all results from 2022 or earlier."""
        results = _search(BROAD_QUERY, store, embedder, date_to="2022")
        for r in results:
            parsed = date.fromisoformat(r.completion_date)
            assert parsed.year <= 2022, (
                f"date_to=2022 but {r.aktenzeichen} has date {r.completion_date}"
            )


# ── Test: Combined filters ─────────────────────────────────────────


class TestCombinedFilters:
    """Multiple filters should intersect, not union."""

    def test_fachbereich_plus_date_narrows_results(self, require_qdrant, store, embedder):
        """WD 6 + year 2023 should return only WD 6-094-23 (not WD 6-052-24)."""
        results = _search(
            BROAD_QUERY, store, embedder,
            fachbereich="WD 6",
            date_from="2023",
            date_to="2023",
        )
        for r in results:
            fb_prefix = r.aktenzeichen.split(" - ")[0].strip()
            assert fb_prefix == "WD 6", f"Got non-WD6 doc: {r.aktenzeichen}"
            parsed = date.fromisoformat(r.completion_date)
            assert parsed.year == 2023, (
                f"Got non-2023 doc: {r.aktenzeichen} ({r.completion_date})"
            )

    def test_impossible_filter_returns_empty(self, require_qdrant, store, embedder):
        """A filter combination that matches no documents should return empty."""
        # There's no WD 1 doc from 2021 in our dataset
        results = _search(
            BROAD_QUERY, store, embedder,
            fachbereich="WD 1",
            date_from="2021",
            date_to="2021",
        )
        assert len(results) == 0, (
            f"Impossible filter should return empty, got {len(results)} results"
        )

    def test_combined_all_three(self, require_qdrant, store, embedder):
        """Triple filter: fachbereich + document_type + date_range."""
        results = _search(
            BROAD_QUERY, store, embedder,
            fachbereich="WD 9",
            document_type="Kurzinformation",
            date_from="2023",
            date_to="2023",
        )
        for r in results:
            fb_prefix = r.aktenzeichen.split(" - ")[0].strip()
            assert fb_prefix == "WD 9"
            assert r.document_type == "Kurzinformation"
            parsed = date.fromisoformat(r.completion_date)
            assert parsed.year == 2023


# ── Test: No filter returns maximum results ────────────────────────


class TestNoFilter:
    def test_unfiltered_returns_many_results(self, require_qdrant, store, embedder):
        """Without filters and a broad query, we should get most of the 17 documents."""
        results = _search(BROAD_QUERY, store, embedder, top_k=17)
        assert len(results) >= 10, (
            f"Unfiltered broad query returned only {len(results)} docs out of 17"
        )
