"""Build the index the integration tier runs against.

Indexes the fixture corpus into collections of its own, so the assertions have a
known, bounded index to work with and the operator's data is never touched.

    uv run python -m tests.prepare_index            build it if empty
    uv run python -m tests.prepare_index --force    rebuild from scratch

Needs Qdrant reachable and valid AI Hub credentials in .env, since it embeds
every chunk. Expect a few minutes for the fixture corpus. The collections are
left in place afterwards, so later runs start immediately.
"""

import argparse
import contextlib
import logging
import sys

from sentra.config import Settings
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.store import VectorStore
from sentra.services.ingest import run_ingestion
from tests.conftest import DATA_DIR, TEST_COLLECTION, TEST_DOC_COLLECTION, TOTAL_PDFS

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("prepare_index")


def build(force: bool = False) -> int:
    env_path = (DATA_DIR.parents[2] / ".env").resolve()
    settings = Settings(
        _env_file=str(env_path),
        collection_name=TEST_COLLECTION,
        doc_collection_name=TEST_DOC_COLLECTION,
        documents_dir=str(DATA_DIR),
    )

    pdfs = sorted(DATA_DIR.glob("*.pdf"))
    if not pdfs:
        log.error("No PDFs in %s", DATA_DIR)
        return 1
    if len(pdfs) != TOTAL_PDFS:
        log.warning(
            "Fixture corpus has %d PDFs but GROUND_TRUTH describes %d; "
            "they are meant to be the same set",
            len(pdfs),
            TOTAL_PDFS,
        )

    store = VectorStore(settings)
    if force:
        for drop in (store.delete_collection, store.delete_doc_collection):
            # Not there yet is the state we are trying to reach anyway.
            with contextlib.suppress(Exception):
                drop()

    store.ensure_collection()
    store.ensure_doc_collection()

    existing = store.collection_info()["points_count"]
    if existing and not force:
        log.info(
            "'%s' already holds %d points. Use --force to rebuild.",
            TEST_COLLECTION,
            existing,
        )
        return 0

    log.info("Indexing %d fixture documents into '%s'", len(pdfs), TEST_COLLECTION)
    run_ingestion(store, EmbeddingClient(settings), str(DATA_DIR), force=force)

    info = store.collection_info()
    log.info("Done: %d points in '%s'", info["points_count"], TEST_COLLECTION)
    return 0 if info["points_count"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="drop and rebuild")
    return build(force=parser.parse_args().force)


if __name__ == "__main__":
    sys.exit(main())
