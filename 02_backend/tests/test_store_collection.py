"""Unit tests for the shared collection mechanics in the vector store.

These cover the parts that used to be written twice: creating a collection with
its payload indexes, batching an upsert, and paging a scroll. They run offline
against a recording stand-in for the Qdrant client, because the integration tier
needs a live Qdrant with an ingested corpus and therefore never runs on an
ordinary test run.

The point is behaviour preservation: the batch size, the page sizes and the
indexed field lists are asserted against the values the two hand-written halves
used before they were merged.

Run:  uv run pytest tests/test_store_collection.py -v
"""

from dataclasses import dataclass, field
from typing import Any

from sentra.rag.store import (
    CHUNK_INDEXED_FIELDS,
    DOC_INDEXED_FIELDS,
    UPSERT_BATCH_SIZE,
    _Collection,
)


@dataclass
class FakeCollections:
    collections: list[Any]


@dataclass
class FakeNamed:
    name: str


@dataclass
class FakeClient:
    """Records what it was asked to do, and can be told to fail."""

    existing: list[str] = field(default_factory=list)
    pages: list[tuple[list[Any], Any]] = field(default_factory=list)
    raise_on_get_collections: bool = False

    created: list[str] = field(default_factory=list)
    indexes: list[tuple[str, str]] = field(default_factory=list)
    upserts: list[tuple[str, int, bool]] = field(default_factory=list)
    scroll_calls: list[dict] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    def get_collections(self) -> FakeCollections:
        if self.raise_on_get_collections:
            raise ConnectionError("qdrant unreachable")
        return FakeCollections([FakeNamed(n) for n in self.existing])

    def create_collection(self, collection_name: str, vectors_config: Any) -> None:
        self.created.append(collection_name)

    def create_payload_index(
        self, collection_name: str, field_name: str, field_schema: Any
    ) -> None:
        self.indexes.append((collection_name, field_name))

    def upsert(self, collection_name: str, wait: bool, points: list) -> None:
        self.upserts.append((collection_name, len(points), wait))

    def scroll(self, **kwargs):
        self.scroll_calls.append(kwargs)
        return self.pages.pop(0)

    def delete_collection(self, collection_name: str) -> None:
        self.deleted.append(collection_name)


def make(client: FakeClient, name: str = "chunks", fields=CHUNK_INDEXED_FIELDS) -> _Collection:
    return _Collection(client, name, fields)  # type: ignore[arg-type]


class TestEnsure:
    def test_creates_when_missing(self):
        client = FakeClient(existing=[])
        make(client).ensure()
        assert client.created == ["chunks"]

    def test_creates_every_declared_payload_index(self):
        client = FakeClient(existing=[])
        make(client).ensure()
        assert [f for _, f in client.indexes] == list(CHUNK_INDEXED_FIELDS)

    def test_does_nothing_when_already_present(self):
        client = FakeClient(existing=["chunks"])
        make(client).ensure()
        assert client.created == []
        assert client.indexes == []

    def test_other_collections_do_not_count_as_present(self):
        client = FakeClient(existing=["something-else"])
        make(client).ensure()
        assert client.created == ["chunks"]

    def test_the_two_field_lists_are_what_the_halves_used(self):
        """Pins the lists copied out of the two hand-written ensure methods."""
        assert CHUNK_INDEXED_FIELDS == (
            "fachbereich_number",
            "document_type",
            "language",
            "aktenzeichen",
        )
        assert DOC_INDEXED_FIELDS == (
            "aktenzeichen",
            "fachbereich_number",
            "document_type",
        )


class TestExists:
    def test_true_when_present(self):
        assert make(FakeClient(existing=["chunks"])).exists() is True

    def test_false_when_absent(self):
        assert make(FakeClient(existing=[])).exists() is False

    def test_false_rather_than_raising_when_qdrant_is_down(self):
        """Callers use this to ask whether there is anything to read yet."""
        assert make(FakeClient(raise_on_get_collections=True)).exists() is False

    def test_ensure_still_raises_when_qdrant_is_down(self):
        """Unlike exists, startup must fail loudly rather than silently create."""
        client = FakeClient(raise_on_get_collections=True)
        try:
            make(client).ensure()
        except ConnectionError:
            pass
        else:
            raise AssertionError("ensure should not swallow a connection error")
        assert client.created == []


class TestUpsert:
    def test_batches_at_the_configured_size(self):
        client = FakeClient()
        n = UPSERT_BATCH_SIZE * 2 + 50
        written = make(client).upsert([object()] * n)
        assert [count for _, count, _ in client.upserts] == [
            UPSERT_BATCH_SIZE,
            UPSERT_BATCH_SIZE,
            50,
        ]
        assert written == n

    def test_batch_size_is_still_one_hundred(self):
        assert UPSERT_BATCH_SIZE == 100

    def test_a_single_batch_is_one_call(self):
        client = FakeClient()
        make(client).upsert([object()] * 10)
        assert len(client.upserts) == 1

    def test_empty_input_writes_nothing(self):
        client = FakeClient()
        assert make(client).upsert([]) == 0
        assert client.upserts == []

    def test_waits_for_each_batch(self):
        """Ingestion relies on a write being readable immediately afterwards."""
        client = FakeClient()
        make(client).upsert([object()] * 5)
        assert all(wait is True for _, _, wait in client.upserts)

    def test_writes_to_its_own_collection(self):
        client = FakeClient()
        make(client, name="docs").upsert([object()] * 5)
        assert {name for name, _, _ in client.upserts} == {"docs"}


class TestScroll:
    def test_yields_every_point_across_pages(self):
        client = FakeClient(pages=[(["a", "b"], 2), (["c"], None)])
        assert list(make(client).scroll(page_size=2)) == ["a", "b", "c"]

    def test_stops_when_the_offset_comes_back_none(self):
        client = FakeClient(pages=[(["a"], None)])
        list(make(client).scroll(page_size=100))
        assert len(client.scroll_calls) == 1

    def test_passes_the_offset_back_on_the_next_page(self):
        client = FakeClient(pages=[(["a"], "cursor-1"), (["b"], None)])
        list(make(client).scroll(page_size=10))
        assert [c["offset"] for c in client.scroll_calls] == [None, "cursor-1"]

    def test_page_size_reaches_the_client(self):
        client = FakeClient(pages=[([], None)])
        list(make(client).scroll(page_size=1000))
        assert client.scroll_calls[0]["limit"] == 1000

    def test_can_request_a_single_payload_field(self):
        """The doc-summary scans ask for one field rather than the whole payload."""
        client = FakeClient(pages=[([], None)])
        list(make(client).scroll(page_size=1000, with_payload=["source_file"]))
        assert client.scroll_calls[0]["with_payload"] == ["source_file"]

    def test_never_fetches_vectors(self):
        client = FakeClient(pages=[([], None)])
        list(make(client).scroll(page_size=100))
        assert client.scroll_calls[0]["with_vectors"] is False

    def test_empty_collection_yields_nothing(self):
        client = FakeClient(pages=[([], None)])
        assert list(make(client).scroll(page_size=100)) == []


class TestDelete:
    def test_deletes_its_own_collection(self):
        client = FakeClient()
        make(client, name="docs").delete()
        assert client.deleted == ["docs"]
