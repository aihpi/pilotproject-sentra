# Refactor notes

Nothing here is broken, it is all "this will hurt later".

**Status, September 2026.** Feature #9 is finished. Sections 1 to 11 are
closed, 13 is closed apart from the eval module, and two things are open and
marked as such: section 12, deferred with a reason, and the follow-ups in
section 14.

The diagnoses below are kept as they were written, because why each thing was
worth fixing is the part still worth reading. What each became is added under
it, and where the original was wrong the correction is stated rather than
quietly dropped.

| | Was | Became |
|---|---|---|
| 1 Untyped dicts through 4 layers | open | #23 |
| 2 Duplicated logic | open | #41, #43, and two items already fixed upstream |
| 3 VectorStore is two copies of itself | open | #26 |
| 4 Config that lies | open | #24 |
| 5 Prompt duplication | open | #37 |
| 6 Stringly-typed dispatch | open | #47 |
| 7 Three error policies in one router | open | #49, #59 |
| 8 Dead code | open | #16 |
| 9 Small | open | #65 |
| 10 Tooling | open | #10, #12, #13, #15 |
| 11 ExplorerView.tsx = 731 lines | open | #53, #63 |
| **12 Ingestion state singleton** | open | **still open, deliberately** |
| 13 Repo layout for production | open | #18, #21, #55; eval module outstanding |
| **14 Found while doing the above** | — | **some open** |

## Priority

The original ordering, kept for the record. It held up: the cheap independent
items did land first and unblocked the rest.

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

**Done, #23.** `Hit` in `domain/`, plus `ScoredDocument`, `DocumentRecord` and
the rest. The payload converters in `rag/store.py` are now the single place
that decides what is optional, so a missing field cannot mean `""` in one
caller and a KeyError in another.

## 2. Duplicated logic

- AZ-from-filename regex twice: `metadata.py:83` `_FILENAME_RE`, `ingest.py:19` `_FILENAME_AZ_RE`. one shared fn
- AZ formatting (`re.sub(\s+)` + f-string) ×4 in metadata.py → `_format_az()`
- `DocumentSearchResult(...)` written out twice in explorer.py → `_to_result(d)`
- api.ts: 5 explorer fns, same 12 lines, different German error string → `postJson(path, body, label)`

**Done, but only one of these was still open by the time the feature reached
it.** Worth recording, because two of the four had been fixed elsewhere and
the notes did not know:

- the second filename regex went in `a913c3f`, before this feature existed
- `DocumentSearchResult` written out twice went with the domain models in #23,
  which gave it a `from_domain` classmethod
- the AZ formatting was #41, and it turned out to be one idea repeated eight
  times rather than four: five whitespace collapses and three assemblies, all
  collapsing into `_normalize_fachbereich_number` and `_format_az`. It also
  hid a real bug, a filename with a double space producing a malformed
  Aktenzeichen, which then cost the document its Fachbereich name
- api.ts was #43. The suggested name was `postJson`; what it became is one
  `request()` covering GET and POST, since the GETs had the same shape

## 3. VectorStore is two copies of itself

`ensure_collection`/`ensure_doc_collection`, `upsert_chunks`/`upsert_doc_records`,
`delete_collection`/`delete_doc_collection`, 2× identical scroll loops.
`batch_size = 100` inline twice, `limit=100` inline twice → constants.
`search()` filter chain: 3 of 4 cases identical shape → loop.

**Done, #26.** A private `_Collection` holds the mechanics and `VectorStore`
owns two of them. The inline numbers became `UPSERT_BATCH_SIZE`,
`CHUNK_SCROLL_PAGE_SIZE` and `DOC_SCROLL_PAGE_SIZE`, and the last two are
deliberately different: one point per chunk versus one per document.

## 4. Config that lies

`CHUNK_MAX_TOKENS` and `RETRIEVAL_TOP_K` in `.env`, `.env.example`, `config.py` — **read by nobody**.
`chunk_document()` uses its own default; top_k comes from pydantic request models.
`EMBEDDING_DIM = 4096` hardcoded while model name is configurable → wrong-dim collection on model swap.
CORS origins hardcoded `main.py:55`.

**Done, #24.** The settings nothing read were either wired up or removed,
`EMBEDDING_DIM` became `embedding_dim` with a startup check that refuses a
collection of the wrong width, and CORS origins moved into settings.

## 5. Prompt duplication

Both system prompts copy-pasted into `ExplorerView.tsx:195` with a comment saying they must match.
→ `GET /api/prompts`. Same for `REFERAT_OPTIONS` / `DOCUMENT_TYPE_OPTIONS` vs `FACHBEREICH_NAMES` / `DOCUMENT_TYPES`.

**Done, #37, as `GET /api/config` rather than `/api/prompts`,** because the
filter options belong with it and the UI needs all of it at mount.

The prompts were still byte-identical when the endpoint was written, so that
half was prevention. The options were not: the frontend offered `Sonstiges`
and the backend's list did not, because `DOCUMENT_TYPES` is what the extractor
looks for and the fallback it writes when it finds none of them is a fifth
value. 221 of 1936 documents carry it, so serving the detection list would
have hidden 11% of the corpus behind a filter.

## 6. Stringly-typed dispatch

`explorer.py:238` `getattr(generator, generator_method)(...)`, method name passed as a string.
→ pass the bound method. type checker and rename refactor start working.

**Done, #47.** The bound method is passed and described by an `AnswerMethod`
protocol. `generator` was only ever there to be `getattr`'d, so it went too.
A typo, a rename, or a method of the wrong shape are now all type errors;
before, the rename failed at runtime after the embedding call and the vector
search had already been paid for.

## 7. Three error policies in one router

- `list_documents`: catches bare `Exception` → `[]`. unreachable Qdrant ≡ empty index
- `health`: catches → `degraded`
- 5 explorer endpoints: catch nothing → 500 + stack trace

→ one app-level handler, 503 for store/hub failures. frontend currently cannot tell "empty" from "down".

**Done, #49,** with the frontend half in #59.

Two endpoints keep their own behaviour on purpose: `/health` still answers 200
with `degraded`, because an endpoint that reports on dependencies is useless
if it fails when they do and the k8s probes read it, and `/documents` still
answers an empty list when no collection exists, but by asking rather than by
catching everything.

Removing the router's `try/except` did not fix `/documents`. The same swallow
was one layer down in `_Collection.exists`, and only live testing caught that:
the unit tests passed because the stub raised where the real code swallowed.
`exists` now takes `tolerate_unreachable`, so which question is being asked is
visible at the call site.

## 8. Dead code

- `AnswerGenerator.generate()` + `SYSTEM_PROMPT` — unused
- `PdfViewer.tsx` — imported by nobody, and duplicated `pdfUrl()` besides
- `submitFeedback()`, `checkHealth()` — exported, never called. `/api/feedback` works, no UI
- `IngestionProgress.stale_documents` — computed, logged, absent from the response model

**Done, #16.** All four. `/api/health` stayed, because the k8s liveness,
readiness and startup probes read it; only the unused frontend client went.

Wiring the feedback UI found something the notes had not: the endpoint had
never worked outside a container. `feedback_file` and `documents_dir` both
defaulted to `/data/...`, which does not exist on a developer machine, so the
first POST answered 500 on `mkdir`. No feedback had ever been recorded
anywhere.

`stale_documents` reaching the response model also revealed that the detection
behind it had never run in the steady state. That became #45.

## 9. Small

- imports inside function bodies: `FileResponse`, `datetime` in routes.py, `Path` in `_run_ingestion_inner`
- missing annotations: `_extract_furniture_text(doc)`, `_store_doc_record(…, metadata, …)`
- two `OpenAI()` clients, embeddings has `timeout=60.0`, generator has none → hanging call blocks forever

**Done, #65.** With one correction: "blocks forever" is wrong. The openai
client applies its own default of 600 seconds for reads when none is given, so
generation was bounded at ten minutes rather than unbounded. Still the wrong
number for a request someone is watching a spinner for, and the frontend sets
no timeout of its own, so the browser waits exactly as long as the backend
does. Both clients now take their timeout from settings: 60 seconds for
embedding, 120 for generation, each measured against the live hub rather than
picked. Embedding one query takes about 0.2 seconds; an answer or an overview
takes 20 to 29 seconds over six samples.

The annotations came with `disallow_untyped_defs`, which is the durable part.
An unannotated parameter is silently `Any`, so mypy checked nothing about it
and said nothing either, which is why two of these sat unannotated since
before `domain/` existed to name their types. Turning it on cost four
annotations across 22 modules.

## 10. Tooling — do this first

- `ruff` is a dev dep with no `[tool.ruff]`. `.mypy_cache/` committed, no mypy config, not gitignored
- `numpy` + `pypdfium2` imported directly, only present transitively via docling
- **no CI runs the tests.** ~100 offline tests, `pytest -m "not integration"`, 30s job
- ports inconsistent 4 ways: README 3000/8000, compose 5173/8001, CORS 3000+5173, vite proxy 8001
- 4 env files, only root used by compose while conftest reads the backend one

**Done: #10 ruff and mypy, #12 CI, #13 the two direct dependencies, #15 the
ports and env files.** Two counts here are now stale rather than wrong: CI has
run the offline tier since #12, and that tier is 287 tests, not ~100. The env
files collapsed to one, `backend/.env`, read by compose, local runs and the
tests alike.

## 11. ExplorerView.tsx = 731 lines

Autocomplete + FilterBar + prompt dialog + submode tables + both prompts + search orchestration.
→ split into `explorer/`.

**Done, #53.** 328 lines, with nothing in the folder over 120. Two of the
seven new files are moves and the rest extractions, which is worth separating:
a move cannot change behaviour and an extraction can. The search area stayed
put, because pulling it out meant fifteen props, which is the sign of a seam
in the wrong place.

#63 then covered the extracted components, which is the thing the split made
possible: vitest and testing-library, 26 tests, and CI runs them. Writing them
found that the filter triggers had no accessible name and that their
`placeholder` props can never display, since the value is never empty.

## 12. Ingestion state singleton

`_progress` module global, `run_ingestion` **rebinds** it via `global`. Anything holding the
object from `get_ingestion_progress()` sees the old one. Doesn't survive 2 replicas.

**Still open, deliberately.** The diagnosis is unchanged and correct.

Fixing it properly means moving that state out of the process, which is a
design decision about what SENTRA runs on rather than a leftover of this
refactor. #51 took the orchestration out of the request handler and put the
job object on `app.state`, partly so there is somewhere for this state to go
when someone takes it on, and the mutual exclusion it added is honest about
being single-process.

## 13. Repo layout for production

**Numbers encode 4 different kinds of thing:** `00_aisc` branding, `01/02` deployables,
`03_data` input data, `04_experiments` scratch. Can't tell what ships.

~~Target: names not numbers.~~ **Superseded by #55.** The original proposal was

```
sentra/   web/          ← ship
infra/  docs/  notebooks/  brand/   ← don't
```

and `sentra/` and `web/` were considered and rejected. `sentra/src/sentra`
reads badly, the repository is already sentra so naming one subfolder after it
implies the other is not part of it, and `backend`/`frontend` is legible to
whoever inherits this without being told. What was built:

```
backend/  frontend/   k8s/   docker-compose.yml     ← ship
data/  docs/  notebooks/  brand/                    ← don't
```

**13.2 Boundaries are fiction — the important part**
- `rag/store.py:20` `from sentra.ingestion.chunker import Chunk` — storage knows the chunker
- `services/explorer.py:13` imports 5 DTOs from `sentra.api.models` — service depends on HTTP layer
- `api/routes.py:72` spawns the ingestion thread in the request handler → `jobs/`

Root cause: no `domain/`, so types parked where first needed. Fixing it is a prerequisite for §1 and for eval.
Then import-linter contracts in CI: `api → explorer → {retrieval, generation, ingestion} → domain → config`, nothing back up.

**Done: #18 both inverted imports and `domain/`, #21 the contracts, #51 the
job.** The contract as built is `main → api → services → {rag | ingestion} →
(evaluation) → domain → config`, and it runs in pre-commit rather than only in
CI. `rag` and `ingestion` are siblings that may not import each other, which
the `|` delimiter expresses; `:` would have let them, and getting that
backwards passes silently.

Moving the job also closed a race the notes had not spotted. The handler read
the progress status, decided nothing was running, and spawned a thread, with
nothing holding the two steps together and the status only being set from
inside the new thread. Two requests arriving together both started a run,
reproduced about one attempt in three.

**13.3 Eval under a monolith** — one app, `evaluation` module. Judge independence = settings block + boot assert + test, not process isolation. Runner still over HTTP.

**Outstanding.** The layering contract already reserves an optional
`(evaluation)` layer just above `domain`, so the module has a place to land
without a contract change. Branch `8-add-the-sentraevaluation-module-skeleton`
exists and is empty.

**13.4 Data out of the repo.** 17 PDFs tracked, `./03_data:/data` bind mount. Note: `conftest.py` `GROUND_TRUTH` is keyed to those exact filenames.

**Done: #28 moved the fixture corpus into `backend/tests/fixtures/corpus`, #29
stopped tracking the data folder, #33 gave the integration tier its own
collection** so it never reads whatever the operator has ingested. The bind
mount is now `./data:/data`.

**13.5 Infra blockers**
- Qdrant publishes 6333/6334 to host, dashboard unauthenticated
- `depends_on: service_started` + lifespan calling `ensure_collection()` → cold start race. need healthcheck + `service_healthy`
- one compose file with dev bind mounts baked in
- no image build / smoke test in CI

**Partly done.** #30 pinned the server image and matched the client version,
after finding all three of server, client floor and manifest disagreeing. The
README now says the dashboard is unauthenticated and its ports are published.
The cold-start race, the single compose file and the missing image smoke test
are **open**.

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

**Steps 1, 3, 4, 5 and 7 done; 6 done differently; 2 and 8 open.** The order
held: 3 and 4 before the rename was right, and by the time #55 ran, the
prediction about what step 5 touches was accurate except for the Dockerfiles,
which needed nothing because both use only paths relative to their build
context. Step 6 became markers rather than directories, which keeps one
conftest and one fixture set.

## 14. Found while doing the above

None of these were in the original notes. They are what the feature actually
turned up, which is the argument for reading code rather than only planning
against it.

**Fixed.**

- The feedback endpoint had never worked outside a container, so no feedback
  had ever been recorded (#16).
- Stale-document detection had never run in the steady state. It sat below a
  return that fires whenever every file is already indexed, added two months
  after that return, so it was born unreachable on the common path. The live
  index had 17 orphans and reported none (#45).
- Two concurrent ingest requests could both start a run (#51).
- A Qdrant blip between the skip-filter lookup and `ensure_collection` made
  ingestion re-parse and re-embed the whole corpus and report success (#61).
- A filename with a double space produced a malformed Aktenzeichen, which then
  cost the document its Fachbereich name (#41).
- `npx tsc --noEmit` checks nothing here: the root tsconfig uses project
  references with `"files": []`, so it exits 0 without reading any code. Use
  `tsc -b`. Recorded in the README (#57).

**Open.**

- 17 documents are indexed with no file on disk and nothing deletes them.
  Every ingestion run now reports them. A delete path belongs to the
  source-management feature.
- `pre-commit run --all-files` works from `git ls-files`, so a new file that
  is still untracked is invisible to every hook. Run `git add` first. This is
  how #37 merged with an unused import.
- `useExplorerSearch` is untested. It owns the five-way endpoint dispatch and
  is the most valuable thing left to cover; it needs the API module mocked.
- The 16 `npm audit` findings in the frontend predate all of this.
