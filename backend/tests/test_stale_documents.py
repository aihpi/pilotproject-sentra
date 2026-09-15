"""Stale-document detection: documents in Qdrant with no file on disk.

The check existed for four months without ever running. It sat at the end of
run_ingestion, below a return that fires whenever every file on disk is
already indexed, and that is the steady state of a working deployment. The
case it was written for, a fully ingested corpus that has since lost files,
was precisely the case it could not see.

So these tests are organised by which path through run_ingestion is taken,
because that, rather than any calculation, is what the bug was about.

Offline: the "nothing to process" path parses no documents at all, and the
other paths get a stubbed parse_pdfs, so no Docling and no AI Hub.
"""

from dataclasses import dataclass

import pytest

from sentra.services import ingest
from sentra.services.ingest import (
    _record_stale_documents,
    get_ingestion_progress,
    run_ingestion,
)


@dataclass
class FakeStore:
    """Only the four methods run_ingestion reaches before it parses anything."""

    indexed: set[str]

    def get_indexed_source_files(self) -> set[str]:
        return set(self.indexed)

    def ensure_collection(self) -> None:
        pass

    def ensure_doc_collection(self) -> None:
        pass


class FakeEmbedder:
    pass


@pytest.fixture
def corpus(tmp_path):
    """Three PDFs on disk. Contents are irrelevant: nothing parses them."""
    for name in ("WD 1-001-20.pdf", "WD 2-002-21.pdf", "WD 3-003-22.pdf"):
        (tmp_path / name).write_bytes(b"%PDF-1.4 not a real pdf")
    return tmp_path


@pytest.fixture
def ingest_settings(settings, corpus):
    return settings.model_copy(update={"documents_dir": str(corpus)})


def run(store, ingest_settings, force=False):
    run_ingestion(store, FakeEmbedder(), ingest_settings, force=force)
    return get_ingestion_progress()


class TestNothingToProcess:
    """The path the bug lived on, and the one that matters in practice."""

    def test_reports_stale_when_everything_is_already_indexed(self, ingest_settings, corpus):
        on_disk = {p.name for p in corpus.glob("*.pdf")}
        store = FakeStore(indexed=on_disk | {"deleted-a.pdf", "deleted-b.pdf"})

        progress = run(store, ingest_settings)

        assert progress.skipped == 3
        assert progress.processed == 0
        assert progress.stale_documents == ["deleted-a.pdf", "deleted-b.pdf"]

    def test_silent_when_the_index_matches_disk(self, ingest_settings, corpus):
        store = FakeStore(indexed={p.name for p in corpus.glob("*.pdf")})

        progress = run(store, ingest_settings)

        assert progress.skipped == 3
        assert progress.stale_documents == []

    def test_warns_in_the_log_too(self, ingest_settings, corpus, caplog):
        """The log line was skipped by the same return, so the drift was
        invisible to anyone reading logs rather than calling the API."""
        on_disk = {p.name for p in corpus.glob("*.pdf")}
        store = FakeStore(indexed=on_disk | {"deleted.pdf"})

        with caplog.at_level("WARNING"):
            run(store, ingest_settings)

        assert "stale documents" in caplog.text
        assert "deleted.pdf" in caplog.text


class TestSomethingToProcess:
    def test_reports_stale_alongside_the_new_work(self, ingest_settings, corpus, monkeypatch):
        """One file is new, so the run goes through the processing loop. The
        stale set must come out the same as on the skip-everything path."""
        monkeypatch.setattr(ingest, "parse_pdfs", lambda *a, **k: iter(()))
        indexed = {"WD 1-001-20.pdf", "WD 2-002-21.pdf", "deleted.pdf"}
        store = FakeStore(indexed=indexed)

        progress = run(store, ingest_settings)

        assert progress.skipped == 2
        assert progress.stale_documents == ["deleted.pdf"]


class TestForcedRun:
    def test_reports_nothing_stale(self, ingest_settings, monkeypatch):
        """force=True never loads the indexed set, so every document would
        look stale. Reporting the whole corpus as missing would be worse than
        reporting nothing, hence the empty-set guard.
        """
        monkeypatch.setattr(ingest, "parse_pdfs", lambda *a, **k: iter(()))
        store = FakeStore(indexed={"deleted.pdf"})

        progress = run(store, ingest_settings, force=True)

        assert progress.skipped == 0
        assert progress.stale_documents == []


class TestEmptyDocumentsDir:
    def test_does_not_call_the_whole_index_stale(self, settings, tmp_path):
        """An unmounted volume or a mis-set DOCUMENTS_DIR looks exactly like a
        corpus whose every document was deleted. Crying wolf there would make
        the field useless, so it stays empty.
        """
        empty = settings.model_copy(update={"documents_dir": str(tmp_path)})
        store = FakeStore(indexed={"a.pdf", "b.pdf"})

        progress = run(store, empty)

        assert progress.stale_documents == []
        assert "No PDF files found" in progress.errors


class TestRecordStaleDocumentsDirectly:
    """The helper takes both sets as arguments so that it cannot become
    position-dependent again."""

    def setup_method(self):
        ingest._progress.stale_documents = []

    def test_difference_is_sorted(self):
        _record_stale_documents({"c.pdf", "a.pdf", "b.pdf"}, {"b.pdf"})
        assert ingest._progress.stale_documents == ["a.pdf", "c.pdf"]

    def test_no_difference(self):
        _record_stale_documents({"a.pdf"}, {"a.pdf", "b.pdf"})
        assert ingest._progress.stale_documents == []

    @pytest.mark.parametrize(
        ("indexed", "on_disk"),
        [(set(), {"a.pdf"}), ({"a.pdf"}, set()), (set(), set())],
        ids=["empty index", "empty directory", "both empty"],
    )
    def test_empty_set_means_silence(self, indexed, on_disk):
        _record_stale_documents(indexed, on_disk)
        assert ingest._progress.stale_documents == []
