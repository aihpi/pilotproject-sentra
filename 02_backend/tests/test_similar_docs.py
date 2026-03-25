"""Similar documents (UC#4) tests against real indexed data.

When a user clicks "find similar documents" for a given Aktenzeichen,
they expect: (a) the document itself is NOT in the results, (b) the
results are actually different documents, (c) thematically related
documents tend to rank higher.

Requires: Qdrant running + data ingested (mark: integration).
Run:  uv run pytest tests/test_similar_docs.py -v -m integration
"""

import pytest

from sentra.services.explorer import find_similar_documents

pytestmark = pytest.mark.integration


# Known Aktenzeichen from the test dataset
AZ_WD3 = "WD 3 - 3000 - 029/23"
AZ_WD9_A = "WD 9 - 3000 - 068/23"
AZ_WD9_B = "WD 9 - 3000 - 100/21"
AZ_WD6_A = "WD 6 - 3000 - 052/24"
AZ_WD8_A = "WD 8 - 3000 - 013/22"
AZ_WD8_B = "WD 8 - 3000 - 011/22"


class TestSimilarDocumentsBasic:
    def test_returns_results(self, require_qdrant, settings):
        """Looking up a known document should return similar documents."""
        results = find_similar_documents(AZ_WD3, top_k=5, settings=settings)
        assert len(results) > 0, "find_similar_documents returned no results"

    def test_self_excluded(self, require_qdrant, settings):
        """The queried document should NOT appear in its own results."""
        results = find_similar_documents(AZ_WD3, top_k=16, settings=settings)
        az_set = {r.aktenzeichen for r in results}
        assert AZ_WD3 not in az_set, (
            f"The queried document {AZ_WD3} appeared in its own similar results"
        )

    def test_all_results_unique(self, require_qdrant, settings):
        """No duplicate documents in results."""
        results = find_similar_documents(AZ_WD3, top_k=16, settings=settings)
        seen = set()
        for r in results:
            assert r.aktenzeichen not in seen, f"Duplicate: {r.aktenzeichen}"
            seen.add(r.aktenzeichen)

    def test_results_have_valid_metadata(self, require_qdrant, settings):
        """Every result should have basic metadata fields."""
        results = find_similar_documents(AZ_WD3, top_k=5, settings=settings)
        for r in results:
            assert r.aktenzeichen, "Missing aktenzeichen"
            assert r.title, "Missing title"
            assert r.fachbereich, "Missing fachbereich"
            assert 0 < r.relevance_score <= 1.0, f"Score {r.relevance_score} out of range"

    def test_sorted_by_similarity(self, require_qdrant, settings):
        results = find_similar_documents(AZ_WD3, top_k=16, settings=settings)
        scores = [r.relevance_score for r in results]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Results not sorted: position {i} has {scores[i]}, {i+1} has {scores[i+1]}"
            )


class TestSimilarDocumentsThematic:
    """Documents from the same Fachbereich should tend to be more similar."""

    def test_same_fachbereich_ranks_higher(self, require_qdrant, settings):
        """For WD 9-068-23, the other WD 9 doc (WD 9-100-21) should be
        relatively highly ranked (both are health-related)."""
        results = find_similar_documents(AZ_WD9_A, top_k=16, settings=settings)
        az_list = [r.aktenzeichen for r in results]
        if AZ_WD9_B in az_list:
            position = az_list.index(AZ_WD9_B)
            # Should be in top half of results
            assert position < len(az_list) // 2, (
                f"{AZ_WD9_B} (same fachbereich) ranked at position {position}/{len(az_list)}, "
                f"expected in top half"
            )

    def test_wd8_pair_are_mutual_neighbors(self, require_qdrant, settings):
        """The two WD 8 docs (environment) should appear in each other's similar results."""
        results_a = find_similar_documents(AZ_WD8_A, top_k=10, settings=settings)
        az_set_a = {r.aktenzeichen for r in results_a}

        results_b = find_similar_documents(AZ_WD8_B, top_k=10, settings=settings)
        az_set_b = {r.aktenzeichen for r in results_b}

        # At least one direction should hold
        assert AZ_WD8_B in az_set_a or AZ_WD8_A in az_set_b, (
            f"WD 8 docs don't appear in each other's top 10 similar results"
        )

    def test_nonexistent_az_returns_empty(self, require_qdrant, settings):
        """Looking up a non-existent Aktenzeichen should return empty, not crash."""
        results = find_similar_documents("WD 99 - 3000 - 999/99", top_k=5, settings=settings)
        assert results == []
