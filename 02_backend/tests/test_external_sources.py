"""External sources (UC#6) tests against real indexed data.

When a user searches for external URLs cited in documents, every returned
URL must be a valid external link (not bundestag.de), and every citing
document must actually exist in the index.

Requires: Qdrant running + data ingested (mark: integration).
Run:  uv run pytest tests/test_external_sources.py -v -m integration
"""

import re

import pytest

from sentra.services.explorer import find_external_sources

pytestmark = pytest.mark.integration


BROAD_QUERY = "Recht Gesetzgebung Deutschland"


class TestExternalSourcesBasic:
    def test_returns_results_for_broad_query(self, require_qdrant, store, embedder):
        """A broad query against 17 docs should find at least some external URLs."""
        results = find_external_sources(
            query=BROAD_QUERY,
            date_from=None,
            date_to=None,
            store=store, embedder=embedder,
        )
        # Some documents may not have external URLs — this is acceptable.
        # But with 17 docs, at least a few should.
        # We test > 0 as a baseline; if all 17 docs truly have no URLs, this
        # would correctly fail and signal a data/extraction problem.
        assert len(results) > 0, "Broad query against 17 docs should find external URLs"

    def test_urls_are_valid_format(self, require_qdrant, store, embedder):
        results = find_external_sources(
            query=BROAD_QUERY, date_from=None, date_to=None, store=store, embedder=embedder,
        )
        for r in results:
            assert r.url.startswith("http://") or r.url.startswith("https://"), (
                f"Invalid URL: '{r.url}'"
            )

    def test_urls_have_real_domain(self, require_qdrant, store, embedder):
        """Every URL must contain a domain with at least one dot.

        This catches the truncation bug where 'https://www.example.com'
        was stored as 'https://www' — structurally valid but useless.
        """
        domain_re = re.compile(r"^https?://([^/:]+)")
        results = find_external_sources(
            query=BROAD_QUERY, date_from=None, date_to=None, store=store, embedder=embedder,
        )
        for r in results:
            m = domain_re.match(r.url)
            assert m, f"Cannot extract domain from URL: '{r.url}'"
            domain = m.group(1)
            assert "." in domain, (
                f"URL has no real domain (truncated?): '{r.url}' — domain='{domain}'"
            )

    def test_urls_have_no_backslash_escapes(self, require_qdrant, store, embedder):
        r"""URLs should not contain Docling markdown artifacts like \_."""
        results = find_external_sources(
            query=BROAD_QUERY, date_from=None, date_to=None, store=store, embedder=embedder,
        )
        for r in results:
            assert "\\_" not in r.url, (
                f"URL contains backslash-escaped underscore: '{r.url}'"
            )

    def test_no_internal_bundestag_urls(self, require_qdrant, store, embedder):
        """URLs from bundestag.de/dserver.bundestag.de should be filtered out during ingestion."""
        excluded = {"bundestag.de", "dserver.bundestag.de", "dip.bundestag.de", "www.bundestag.de"}
        results = find_external_sources(
            query=BROAD_QUERY, date_from=None, date_to=None, store=store, embedder=embedder,
        )
        for r in results:
            domain_match = re.match(r"https?://([^/:]+)", r.url)
            if domain_match:
                domain = domain_match.group(1).lower()
                assert domain not in excluded, (
                    f"Internal URL leaked through: '{r.url}'"
                )

    def test_every_source_has_citing_docs(self, require_qdrant, store, embedder):
        """Every URL must be cited by at least one document."""
        results = find_external_sources(
            query=BROAD_QUERY, date_from=None, date_to=None, store=store, embedder=embedder,
        )
        for r in results:
            assert len(r.cited_in) >= 1, (
                f"URL '{r.url}' has zero citing documents"
            )

    def test_citing_docs_have_valid_aktenzeichen(self, require_qdrant, store, embedder):
        """Every citing document should have a valid Aktenzeichen."""
        az_pattern = re.compile(r"^(WD|EU)\s+\d+\s+-\s+3000\s+-\s+\d+/\d+$")
        results = find_external_sources(
            query=BROAD_QUERY, date_from=None, date_to=None, store=store, embedder=embedder,
        )
        for r in results:
            for doc in r.cited_in:
                assert az_pattern.match(doc.aktenzeichen), (
                    f"Citing doc has invalid AZ: '{doc.aktenzeichen}'"
                )
                assert doc.title, f"Citing doc {doc.aktenzeichen} has empty title"


class TestExternalSourcesSorting:
    def test_sorted_by_citation_count(self, require_qdrant, store, embedder):
        """Results should be sorted by number of citing documents (descending)."""
        results = find_external_sources(
            query=BROAD_QUERY, date_from=None, date_to=None, store=store, embedder=embedder,
        )
        if len(results) < 2:
            pytest.skip("Not enough URLs to test sorting")
        counts = [len(r.cited_in) for r in results]
        for i in range(len(counts) - 1):
            assert counts[i] >= counts[i + 1], (
                f"URLs not sorted by citation count: position {i} has {counts[i]}, "
                f"position {i+1} has {counts[i+1]}"
            )


class TestExternalSourcesFiltered:
    def test_filters_apply_to_source_search(self, require_qdrant, store, embedder):
        """Filtering by fachbereich should limit which documents' URLs are returned."""
        results = find_external_sources(
            query=BROAD_QUERY, date_from=None, date_to=None,
            store=store, embedder=embedder, fachbereich="WD 8",
        )
        # Every citing document should be from WD 8
        for r in results:
            for doc in r.cited_in:
                fb_prefix = doc.aktenzeichen.split(" - ")[0].strip()
                assert fb_prefix == "WD 8", (
                    f"Filtered for WD 8 but URL '{r.url}' is cited by {doc.aktenzeichen}"
                )
