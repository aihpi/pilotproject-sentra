"""A date filter is applied, or the request fails. It is never quietly dropped.

DateRange declared both bounds as plain strings with no validator, so a value
like "2O23" or "20223" reached rag/store.py, failed to parse there, and the
date condition was simply never added to the query. The search then ran across
the whole corpus and answered 200 with documents from every year. The only
trace was a warning in a log nobody is reading while they search.

The explorer UI could not produce this: FilterBar renders a year dropdown. It
was reachable from anything talking to the API directly, which is what the
evaluation harness does for every case in a round.

Offline. The endpoint tests inject a stub store, and the one test that uses a
real VectorStore never reaches Qdrant — the parse happens while the filter is
being built, before any call goes out.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sentra.api.models import DateRange
from sentra.api.routes import get_embedder, get_generator, get_store, router
from sentra.config import get_settings
from sentra.rag.store import VectorStore

# Every explorer endpoint that accepts a date range. /explorer/similar is the
# one that does not: it searches by Aktenzeichen and takes no filters.
DATE_FILTERED_ENDPOINTS = [
    "/api/explorer/documents",
    "/api/explorer/sources",
    "/api/explorer/answer",
    "/api/explorer/overview",
]

# Both halves of the bug, and both plausible as typing mistakes. "2O23" is the
# letter O; "20223" is a digit too many and parses as an int perfectly well,
# only to be rejected by date() as a year out of range.
BAD_YEARS = ["2O23", "20223", "202", "0000", " 2023", "2023-01-01", "letztes Jahr"]


class RecordingStore:
    """Answers every search with nothing, and remembers what it was asked."""

    def __init__(self) -> None:
        self.searches: list[dict] = []

    def search(self, **kwargs) -> list:
        self.searches.append(kwargs)
        return []

    def get_doc_records_by_aktenzeichen(self, aktenzeichen: list[str]) -> list:
        return []


class WorkingEmbedder:
    def embed_query(self, query: str) -> list[float]:
        return [0.0, 1.0]


class WorkingGenerator:
    def generate_answer(self, question: str, context: str, system_prompt=None) -> str:
        return "eine Antwort"

    def generate_overview(self, topic: str, context: str, system_prompt=None) -> str:
        return "ein Überblick"


@pytest.fixture
def store() -> RecordingStore:
    return RecordingStore()


@pytest.fixture
def client(settings, store):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_embedder] = lambda: WorkingEmbedder()
    app.dependency_overrides[get_generator] = lambda: WorkingGenerator()
    return TestClient(app)


# ── The model ───────────────────────────────────────────────────────


class TestDateRangeAcceptsAYear:
    def test_a_four_digit_year(self):
        assert DateRange(date_from="2023", date_to="2024").date_from == "2023"

    def test_no_bounds_at_all(self):
        assert DateRange().date_from is None

    def test_one_bound_only(self):
        assert DateRange(date_from="2024").date_to is None

    def test_an_empty_string_is_no_bound(self):
        """The store already read "" as falsy and filtered on nothing, so the
        effect is unchanged and "" is not an error. It normalises to None so
        that everything downstream sees one spelling of "no bound"."""
        assert DateRange(date_from="", date_to="").date_from is None


class TestDateRangeRejectsEverythingElse:
    @pytest.mark.parametrize("value", BAD_YEARS)
    def test_date_from(self, value):
        with pytest.raises(ValidationError):
            DateRange(date_from=value)

    @pytest.mark.parametrize("value", BAD_YEARS)
    def test_date_to(self, value):
        with pytest.raises(ValidationError):
            DateRange(date_to=value)


# ── The endpoints ───────────────────────────────────────────────────


class TestABadYearIsRejected:
    """Was a 200 with results from every year in the corpus."""

    @pytest.mark.parametrize("path", DATE_FILTERED_ENDPOINTS)
    def test_answers_422(self, client, path):
        response = client.post(path, json={"query": "Redezeit", "date_range": {"date_from": "2O23"}})

        assert response.status_code == 422

    @pytest.mark.parametrize("path", DATE_FILTERED_ENDPOINTS)
    def test_names_the_field_that_was_wrong(self, client, path):
        response = client.post(path, json={"query": "Redezeit", "date_range": {"date_from": "2O23"}})

        assert "date_from" in str(response.json()["detail"])

    @pytest.mark.parametrize("path", DATE_FILTERED_ENDPOINTS)
    def test_nothing_is_searched(self, client, store, path):
        """The point of the fix. The old code searched, unfiltered, and
        returned what it found."""
        client.post(path, json={"query": "Redezeit", "date_range": {"date_to": "20223"}})

        assert store.searches == []


class TestAGoodYearStillSearches:
    @pytest.mark.parametrize("path", DATE_FILTERED_ENDPOINTS)
    def test_answers_200(self, client, path):
        response = client.post(
            path, json={"query": "Redezeit", "date_range": {"date_from": "2023", "date_to": "2023"}}
        )

        assert response.status_code == 200

    @pytest.mark.parametrize("path", DATE_FILTERED_ENDPOINTS)
    def test_the_filter_reaches_the_store(self, client, store, path):
        client.post(
            path, json={"query": "Redezeit", "date_range": {"date_from": "2022", "date_to": "2023"}}
        )

        assert store.searches, f"{path} did not search at all"
        assert store.searches[0]["date_from"] == "2022"
        assert store.searches[0]["date_to"] == "2023"

    @pytest.mark.parametrize("path", DATE_FILTERED_ENDPOINTS)
    def test_no_date_range_searches_without_one(self, client, store, path):
        client.post(path, json={"query": "Redezeit"})

        assert store.searches[0]["date_from"] is None
        assert store.searches[0]["date_to"] is None


# ── The store ───────────────────────────────────────────────────────


class TestTheStoreRefusesToUnfilter:
    """The API cannot reach this any more, and something else will.

    Qdrant does not have to be running: search raises while assembling the
    filter, before it queries anything. Constructing the client emits the same
    server-version warning the rest of the offline suite already does.
    """

    @pytest.mark.parametrize("value", ["2O23", "20223", "0000"])
    def test_a_bad_date_from_raises(self, settings, value):
        with pytest.raises(ValueError, match="date_from"):
            VectorStore(settings).search(query_embedding=[0.0, 1.0], date_from=value)

    @pytest.mark.parametrize("value", ["2O23", "20223", "0000"])
    def test_a_bad_date_to_raises(self, settings, value):
        with pytest.raises(ValueError, match="date_to"):
            VectorStore(settings).search(query_embedding=[0.0, 1.0], date_to=value)

    def test_the_message_carries_both_values(self, settings):
        with pytest.raises(ValueError) as caught:
            VectorStore(settings).search(
                query_embedding=[0.0, 1.0], date_from="2O23", date_to="2024"
            )

        assert "'2O23'" in str(caught.value)
        assert "'2024'" in str(caught.value)
