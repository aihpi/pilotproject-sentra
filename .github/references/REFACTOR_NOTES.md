# Refactor — short

Full version: `REFACTOR.md`. Nothing here is broken, it is all "this will hurt later".

## Priority

```
cheap + independent   → 10 tooling, 8 dead code, 4 dead config, 5 prompt endpoint
biggest payoff        → 1 typed hits, 13.2 domain/ + layering, 3 store dedup
needs a team decision → 13 repo layout
```

## 1. Untyped dicts through 4 layers

`store.search` → `[{"score":…, **payload}]` → explorer → generator. Inconsistent access:
`explorer.py:47` `r["aktenzeichen"]` but `r.get("document_type","")` two lines later;
`generator.py:69` indexes `r['section_title']` directly.
→ missing field = `""` or KeyError depending on where you land. Want a `ChunkHit` type in `domain/`.

## 2. Duplicated logic

- AZ-from-filename regex twice: `metadata.py:83` `_FILENAME_RE`, `ingest.py:19` `_FILENAME_AZ_RE`. one shared fn
- AZ formatting (`re.sub(\s+)` + f-string) ×4 in metadata.py → `_format_az()`
- `DocumentSearchResult(...)` written out twice in explorer.py → `_to_result(d)`
- api.ts: 5 explorer fns, same 12 lines, different German error string → `postJson(path, body, label)`

## 3. VectorStore is two copies of itself

`ensure_collection`/`ensure_doc_collection`, `upsert_chunks`/`upsert_doc_records`,
`delete_collection`/`delete_doc_collection`, 2× identical scroll loops.
`batch_size = 100` inline twice, `limit=100` inline twice → constants.
`search()` filter chain: 3 of 4 cases identical shape → loop.

## 4. Config that lies

`CHUNK_MAX_TOKENS` and `RETRIEVAL_TOP_K` in `.env`, `.env.example`, `config.py` — **read by nobody**.
`chunk_document()` uses its own default; top_k comes from pydantic request models.
`EMBEDDING_DIM = 4096` hardcoded while model name is configurable → wrong-dim collection on model swap.
CORS origins hardcoded `main.py:55`.

## 5. Prompt duplication

Both system prompts copy-pasted into `ExplorerView.tsx:195` with a comment saying they must match.
→ `GET /api/prompts`. Same for `REFERAT_OPTIONS` / `DOCUMENT_TYPE_OPTIONS` vs `FACHBEREICH_NAMES` / `DOCUMENT_TYPES`.

## 6. Stringly-typed dispatch

`explorer.py:238` `getattr(generator, generator_method)(...)`, method name passed as a string.
→ pass the bound method. type checker and rename refactor start working.

## 7. Three error policies in one router

- `list_documents`: catches bare `Exception` → `[]`. unreachable Qdrant ≡ empty index
- `health`: catches → `degraded`
- 5 explorer endpoints: catch nothing → 500 + stack trace

→ one app-level handler, 503 for store/hub failures. frontend currently cannot tell "empty" from "down".

## 8. Dead code

- `AnswerGenerator.generate()` + `SYSTEM_PROMPT` — unused
- `PdfViewer.tsx` — imported by nobody
- `submitFeedback()`, `checkHealth()` — exported, never called. `/api/feedback` works, no UI
- `IngestionProgress.stale_documents` — computed, logged, absent from the response model

## 9. Small

- imports inside function bodies: `FileResponse`, `datetime` in routes.py, `Path` in `_run_ingestion_inner`
- missing annotations: `_extract_furniture_text(doc)`, `_store_doc_record(…, metadata, …)`
- two `OpenAI()` clients, embeddings has `timeout=60.0`, generator has none → hanging call blocks forever

## 10. Tooling — do this first

- `ruff` is a dev dep with no `[tool.ruff]`. `.mypy_cache/` committed, no mypy config, not gitignored
- `numpy` + `pypdfium2` imported directly, only present transitively via docling
- **no CI runs the tests.** ~100 offline tests, `pytest -m "not integration"`, 30s job
- ports inconsistent 4 ways: README 3000/8000, compose 5173/8001, CORS 3000+5173, vite proxy 8001
- 4 env files, only root used by compose while conftest reads the backend one

## 11. ExplorerView.tsx = 731 lines

Autocomplete + FilterBar + prompt dialog + submode tables + both prompts + search orchestration.
→ split into `explorer/`.

## 12. Ingestion state singleton

`_progress` module global, `run_ingestion` **rebinds** it via `global`. Anything holding the
object from `get_ingestion_progress()` sees the old one. Doesn't survive 2 replicas.

## 13. Repo layout for production

**Numbers encode 4 different kinds of thing:** `00_aisc` branding, `01/02` deployables,
`03_data` input data, `04_experiments` scratch. Can't tell what ships.

Target: names not numbers.
```
sentra/   web/          ← ship
infra/  docs/  notebooks/  brand/   ← don't
```

**13.2 Boundaries are fiction — the important part**
- `rag/store.py:20` `from sentra.ingestion.chunker import Chunk` — storage knows the chunker
- `services/explorer.py:13` imports 5 DTOs from `sentra.api.models` — service depends on HTTP layer
- `api/routes.py:72` spawns the ingestion thread in the request handler → `jobs/`

Root cause: no `domain/`, so types parked where first needed. Fixing it is a prerequisite for §1 and for eval.
Then import-linter contracts in CI: `api → explorer → {retrieval, generation, ingestion} → domain → config`, nothing back up.

**13.3 Eval under a monolith** — one app, `evaluation` module. Judge independence = settings block + boot assert + test, not process isolation. Runner still over HTTP.

**13.4 Data out of the repo.** 17 PDFs tracked, `./03_data:/data` bind mount. Note: `conftest.py` `GROUND_TRUTH` is keyed to those exact filenames.

**13.5 Infra blockers**
- Qdrant publishes 6333/6334 to host, dashboard unauthenticated
- `depends_on: service_started` + lifespan calling `ensure_collection()` → cold start race. need healthcheck + `service_healthy`
- one compose file with dev bind mounts baked in
- no image build / smoke test in CI

**13.6 Migration order** (each step stays green)
```
1 docs/ + brand/           zero code refs
2 compose split            ports + healthcheck land here
3 domain/ + fix 2 imports  ← fight for this one
4 import-linter contracts
5 02_backend→sentra, 01_frontend→web
     touches: compose contexts, 2 Dockerfiles, conftest parents[2], documents_dir, README
6 tests/unit + tests/integration, trim fixture corpus
7 04_experiments → notebooks/, optional dep group
8 fold in eval module
```
1–4 worth doing regardless of any rename.
