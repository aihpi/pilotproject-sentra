# Sentra backend

FastAPI application: document ingestion, retrieval over Qdrant, and answer
generation through the AI Hub. See the root `README.md` for the full stack.

## Setup

```bash
uv sync                     # installs the project plus the dev group
cp .env.example .env        # then fill in the AI Hub credentials
```

## Running

```bash
uv run uvicorn sentra.main:app --reload --port 8001
```

Swagger UI is at `/docs`.

## Tests

Two tiers, separated by the `integration` marker.

```bash
uv run pytest -m "not integration"    # offline, 274 tests, no services needed
uv run pytest -m integration          # needs Qdrant and the AI Hub, see below
uv run pytest                         # everything
```

**CI runs the offline tier only.** It needs nothing beyond the lockfile, so it
gates every push and pull request.

### Running the integration tier

These are not in CI, and the reason is cost rather than difficulty: every run
embeds live queries and calls the chat model.

The tier runs against **its own index**, built from the fixture corpus in
`tests/fixtures/corpus`. It does not read whatever you have ingested, and it
cannot modify it. That matters because several assertions only mean something
against a known, bounded index: "these two documents are mutual top-10
neighbours" is a reasonable claim among seventeen documents and close to
meaningless among thousands.

Prerequisites:

1. **Qdrant reachable** at `QDRANT_URL`.
2. **Valid AI Hub credentials** in `.env`, for embedding and generation.

Build the test index once, then run the tier as often as you like:

```bash
docker compose up -d qdrant
uv run python -m tests.prepare_index     # a few minutes, 17 documents
uv run pytest -m integration
```

`prepare_index` writes to `sentra_test_chunks` and `sentra_test_docs`, separate
from whatever `COLLECTION_NAME` points at. It skips the work if the index is
already populated; `--force` drops and rebuilds. The collections are left in
place, so later runs start immediately. Delete them whenever you want the space
back.

If the index is missing or empty the tier skips with a message telling you this,
rather than failing or silently passing.

The tier also asserts against a hand-maintained `GROUND_TRUTH` table in
`tests/conftest.py`, keyed to the exact filenames of the 17 fixture PDFs, so
changing that set means updating the table.

## Lint and type check

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
```

Or all of them at once, the same way CI does it:

```bash
uvx pre-commit run --all-files
```

Install the hook so it runs on every commit:

```bash
uv tool install pre-commit && pre-commit install
```

Seven `# type: ignore` comments in `rag/store.py` are deliberate and temporary.
The Qdrant client types `point.payload` and `point.vector` as Optional while the
code assumes they are present; they are cleared by the typed-hit task. Because
`warn_unused_ignores` is on, they will fail the type check once that lands,
which is the intended signal.
