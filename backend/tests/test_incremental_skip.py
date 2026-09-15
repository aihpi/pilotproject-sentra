"""The skip filter that makes ingestion incremental, and what it costs to get wrong.

get_indexed_source_files reports which documents are already in the index, and
ingestion processes everything it does not name. So an empty set means "process
the whole corpus": on the real data, 1919 documents of Docling parsing and
embedding calls.

It used to return an empty set for a Qdrant it could not reach, on the grounds
that "either way there is nothing to skip". True of a fresh index; false of an
outage, where there is plenty to skip and the question simply went unanswered.

Offline. The store is stubbed, and the parser is replaced with a counter, so
these measure what would have been parsed without parsing anything.
"""

import pytest

from sentra.config import Settings
from sentra.rag.store import DOC_SCROLL_PAGE_SIZE, VectorStore
from sentra.services import ingest


class FakeCollections:
    def __init__(self, names):
        self.collections = [type("N", (), {"name": n})() for n in names]


class FakeClient:
    """Enough of the Qdrant client for the doc-field scroll."""

    def __init__(self, *, existing=("docs",), unreachable=False, payloads=()):
        self._existing = list(existing)
        self._unreachable = unreachable
        self._payloads = list(payloads)

    def get_collections(self):
        if self._unreachable:
            raise ConnectionError("qdrant unreachable")
        return FakeCollections(self._existing)

    def scroll(self, **kwargs):
        points = [type("P", (), {"payload": p})() for p in self._payloads]
        return points, None


def store_with(client) -> VectorStore:
    store = VectorStore(Settings())
    store._docs._client = client
    store._docs.name = "docs"
    return store


class TestTheLookup:
    def test_reports_what_is_indexed(self):
        client = FakeClient(payloads=[{"source_file": "a.pdf"}, {"source_file": "b.pdf"}])
        assert store_with(client).get_indexed_source_files() == {"a.pdf", "b.pdf"}

    def test_absent_collection_is_an_empty_set(self):
        """A first run, before anything has been created. Genuinely nothing to
        skip, and not an error."""
        assert store_with(FakeClient(existing=[])).get_indexed_source_files() == set()

    def test_unreachable_qdrant_raises_instead(self):
        """The change. Silence here is indistinguishable from an empty index,
        and ingestion cannot tell the difference either."""
        with pytest.raises(ConnectionError):
            store_with(FakeClient(unreachable=True)).get_indexed_source_files()

    def test_scrolls_with_the_doc_page_size(self):
        """The doc collection is scrolled a thousand at a time, not a hundred:
        one point per document rather than per chunk."""
        seen = {}
        client = FakeClient(payloads=[{"source_file": "a.pdf"}])
        real_scroll = client.scroll
        client.scroll = lambda **kw: (seen.update(kw), real_scroll(**kw))[1]

        store_with(client).get_indexed_source_files()
        assert seen["limit"] == DOC_SCROLL_PAGE_SIZE


class TestWhatIngestionDoesWithIt:
    """Measured in documents handed to the parser, because that is the cost."""

    @pytest.fixture
    def counting_parser(self, monkeypatch):
        handed: list[str] = []

        def parse(_dir, pdf_paths=None):
            handed.extend(p.name for p in pdf_paths or [])
            return iter(())

        monkeypatch.setattr(ingest, "parse_pdfs", parse)
        return handed

    @pytest.fixture
    def corpus(self, tmp_path):
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            (tmp_path / name).write_bytes(b"%PDF-1.4")
        return tmp_path

    @pytest.fixture
    def settings_for(self, settings, corpus):
        return settings.model_copy(update={"documents_dir": str(corpus)})

    def run(self, indexed, settings_for):
        class Store:
            def get_indexed_source_files(self):
                return set(indexed)

            def ensure_collection(self):
                pass

            def ensure_doc_collection(self):
                pass

        ingest.run_ingestion(Store(), None, settings_for, force=False)
        return ingest.get_ingestion_progress()

    def run_with_real_store(self, client, settings_for):
        """A real VectorStore, so the lookup goes through the real code, with
        only the two ensure calls stubbed out. That pair succeeding while the
        lookup failed is exactly the blip being described."""
        store = store_with(client)
        store.ensure_collection = lambda: None  # type: ignore[method-assign]
        store.ensure_doc_collection = lambda: None  # type: ignore[method-assign]

        ingest.run_ingestion(store, None, settings_for, force=False)
        return ingest.get_ingestion_progress()

    def test_already_indexed_documents_are_not_parsed(self, settings_for, counting_parser):
        progress = self.run({"a.pdf", "b.pdf", "c.pdf"}, settings_for)

        assert progress.skipped == 3
        assert counting_parser == []

    def test_only_the_new_one_is_parsed(self, settings_for, counting_parser):
        progress = self.run({"a.pdf", "b.pdf"}, settings_for)

        assert progress.skipped == 2
        assert counting_parser == ["c.pdf"]

    def test_a_blip_no_longer_re_parses_everything(self, settings_for, counting_parser):
        """The scenario worth the change.

        Qdrant unreachable for the lookup and back by the time
        ensure_collection runs a line later, which a restart produces. The
        lookup used to answer "nothing indexed", so every document was parsed
        again and the run reported completed. It now fails instead, which is
        the honest answer and costs nothing.
        """
        progress = self.run_with_real_store(FakeClient(unreachable=True), settings_for)

        assert counting_parser == [], "the corpus was re-parsed after a blip"
        assert progress.status == "failed"
        assert any("unreachable" in e for e in progress.errors)

    def test_a_first_run_still_parses_everything(self, settings_for, counting_parser):
        """The other side of it. No collection yet is genuinely nothing to
        skip, so all three documents are meant to be parsed. Also through the
        real store, so this and the blip test differ only in whether Qdrant
        answered."""
        progress = self.run_with_real_store(FakeClient(existing=[]), settings_for)

        assert sorted(counting_parser) == ["a.pdf", "b.pdf", "c.pdf"]
        assert progress.skipped == 0
