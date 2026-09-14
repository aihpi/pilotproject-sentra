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
uv run pytest -m "not integration"    # offline, ~133 tests, no services needed
uv run pytest -m integration          # needs Qdrant and the AI Hub, see below
uv run pytest                         # everything
```

**CI runs the offline tier only.** It needs nothing beyond the lockfile, so it
gates every push and pull request.

### Running the integration tier

These are not in CI, and the reason is cost rather than difficulty. They assert
against a corpus that is already indexed, so a fresh Qdrant is not enough:
`conftest.py` checks that the collection exists and skips the whole tier if it
does not, which would make a green run meaningless.

Prerequisites:

1. **Qdrant reachable** at `QDRANT_URL`, with the collection named by
   `COLLECTION_NAME` present.
2. **The corpus ingested** into it. That means a full Docling parse of the PDFs
   in `03_data/Ausarbeitungen` plus an embedding call per chunk, so it takes
   minutes and consumes AI Hub quota.
3. **Valid AI Hub credentials** in `.env`, since the search and answer tests
   embed live queries and call the chat model.

```bash
docker compose up -d qdrant
uv run uvicorn sentra.main:app --port 8001 &
curl -X POST http://localhost:8001/api/ingest      # wait for /api/ingest/status
uv run pytest -m integration
```

The tier also asserts against a hand-maintained `GROUND_TRUTH` table in
`tests/conftest.py`, keyed to the exact filenames of the 17 PDFs, so adding or
renaming a document in that directory means updating the table.

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
