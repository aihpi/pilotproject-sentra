# Refactor notes

A record of the structural problems found in the codebase before feature #9,
what each one became, and which remain open. Nothing listed was broken at the
time of writing. Everything listed was going to cost something later.

Status as of September 2026: feature #9 is finished. Sections 1 to 11 are
closed. Section 13 is closed except for the evaluation module. Section 12 is
deferred with a stated reason, and section 14 holds follow-ups, some of them
still open.

Each diagnosis is kept in the form it was first written, because the reasoning
for why something was worth fixing outlasts the fix. What it became is recorded
beneath it. Where the original diagnosis turned out to be wrong, the correction
is stated rather than removed.

| Section | Status | Closed by |
|---|---|---|
| 1 Untyped dicts through four layers | closed | #23 |
| 2 Duplicated logic | closed | #41, #43, and two already fixed upstream |
| 3 VectorStore is two copies of itself | closed | #26 |
| 4 Configuration that lies | closed | #24 |
| 5 Prompt duplication | closed | #37 |
| 6 Stringly-typed dispatch | closed | #47 |
| 7 Three error policies in one router | closed | #49, #59 |
| 8 Dead code | closed | #16 |
| 9 Small items | closed | #65 |
| 10 Tooling | closed | #10, #12, #13, #15 |
| 11 ExplorerView.tsx at 731 lines | closed | #53, #63 |
| 12 Ingestion state singleton | open, deliberately | |
| 13 Repository layout for production | mostly closed | #18, #21, #55; evaluation module outstanding |
| 14 Found while doing the above | partly open | |

## Priority as originally set

Kept for the record. It held up: the cheap independent items did land first and
did unblock the rest.

```text
cheap and independent  10 tooling, 8 dead code, 4 dead config, 5 prompt endpoint
biggest payoff         1 typed hits, 13.2 domain/ and layering, 3 store dedup
needs a team decision  13 repository layout
```

## 1. Untyped dicts through four layers

`store.search` returned `[{"score": ..., **payload}]`, which passed through the
explorer into the generator. Access was inconsistent: `explorer.py:47` used
`r["aktenzeichen"]` and `r.get("document_type", "")` two lines later, while
`generator.py:69` indexed `r['section_title']` directly. A missing field was
therefore either an empty string or a `KeyError` depending on where execution
landed. The fix wanted was a `ChunkHit` type in `domain/`.

Closed by #23. `Hit` now lives in `domain/`, alongside `ScoredDocument`,
`DocumentRecord` and the rest. The payload converters in `rag/store.py` are the
single place deciding what is optional, so a missing field can no longer mean
an empty string in one caller and an exception in another.

## 2. Duplicated logic

Four instances were listed:

- the Aktenzeichen-from-filename regex existed twice, as `_FILENAME_RE` in
  `metadata.py:83` and `_FILENAME_AZ_RE` in `ingest.py:19`
- Aktenzeichen formatting, a whitespace collapse followed by an f-string,
  appeared four times in `metadata.py`
- `DocumentSearchResult(...)` was written out twice in `explorer.py`
- `api.ts` held five explorer functions of the same twelve lines, differing
  only in a German error string

Only one was still open by the time the feature reached it, which is worth
recording because the notes did not know that.

The second filename regex had gone in `a913c3f`, before this feature existed.
The duplicated `DocumentSearchResult` went with the domain models in #23, which
gave it a `from_domain` classmethod. The Aktenzeichen formatting became #41,
and turned out to be one idea repeated eight times rather than four: five
whitespace collapses and three assemblies, all of which collapsed into
`_normalize_fachbereich_number` and `_format_az`. That work also uncovered a
real defect, where a filename containing a double space produced a malformed
Aktenzeichen, which in turn cost the document its Fachbereich name. The
`api.ts` duplication became #43; the suggested name was `postJson`, and what it
became was a single `request()` covering GET as well, since the GETs had the
same shape.

## 3. VectorStore is two copies of itself

`ensure_collection` and `ensure_doc_collection`, `upsert_chunks` and
`upsert_doc_records`, `delete_collection` and `delete_doc_collection`, plus two
identical scroll loops. `batch_size = 100` appeared inline twice and
`limit=100` twice. Three of the four cases in the `search()` filter chain had
an identical shape and wanted a loop.

Closed by #26. A private `_Collection` holds the mechanics and `VectorStore`
owns two of them. The inline numbers became `UPSERT_BATCH_SIZE`,
`CHUNK_SCROLL_PAGE_SIZE` and `DOC_SCROLL_PAGE_SIZE`. The last two are
deliberately different values, because one is a point per chunk and the other a
point per document.

## 4. Configuration that lies

`CHUNK_MAX_TOKENS` and `RETRIEVAL_TOP_K` appeared in `.env`, `.env.example` and
`config.py`, and were read by nothing: `chunk_document()` used its own default,
and top_k came from the pydantic request models. `EMBEDDING_DIM = 4096` was
hardcoded while the model name was configurable, so swapping the model produced
a collection of the wrong width. CORS origins were hardcoded at `main.py:55`.

Closed by #24. Settings that nothing read were either wired up or removed,
`EMBEDDING_DIM` became `embedding_dim` with a startup check that refuses a
collection of the wrong width, and CORS origins moved into settings.

## 5. Prompt duplication

Both system prompts were copy-pasted into `ExplorerView.tsx:195` under a
comment saying they must match the backend. The same applied to
`REFERAT_OPTIONS` and `DOCUMENT_TYPE_OPTIONS` against `FACHBEREICH_NAMES` and
`DOCUMENT_TYPES`.

Closed by #37, as `GET /api/config` rather than the proposed `/api/prompts`,
because the filter options belong with the prompts and the UI needs all of it
at mount.

The prompts were still byte-identical when the endpoint was written, so that
half was prevention. The options were not. The frontend offered `Sonstiges` and
the backend list did not, because `DOCUMENT_TYPES` is what the extractor looks
for, and the fallback it writes when it finds none of them is a fifth value.
221 of 1936 documents carry that fallback, so serving the detection list would
have hidden 11 percent of the corpus behind a filter.

## 6. Stringly-typed dispatch

`explorer.py:238` called `getattr(generator, generator_method)(...)` with the
method name passed as a string. Passing the bound method instead makes the type
checker and rename refactoring work.

Closed by #47. The bound method is passed and described by an `AnswerMethod`
protocol. The `generator` argument existed only to be the target of `getattr`,
so it went too. A typo, a rename, or a method of the wrong shape are now all
type errors. Previously a rename failed at runtime, after the embedding call
and the vector search had already been paid for.

## 7. Three error policies in one router

`list_documents` caught bare `Exception` and returned `[]`, making an
unreachable Qdrant indistinguishable from an empty index. `health` caught and
reported `degraded`. Five explorer endpoints caught nothing and produced a 500
with a stack trace. The frontend could not tell empty from down.

Closed by #49, with the frontend half in #59.

Two endpoints keep their own behaviour deliberately. `/health` still answers
200 with `degraded`, because an endpoint that reports on dependencies is
useless if it fails when they do, and the Kubernetes probes read it.
`/documents` still answers an empty list when no collection exists, but by
asking rather than by catching everything.

Removing the router's `try`/`except` did not fix `/documents`. The same swallow
sat one layer down in `_Collection.exists`, and only live testing caught it:
the unit tests passed because the stub raised where the real code swallowed.
`exists` now takes `tolerate_unreachable`, so which question is being asked is
visible at the call site.

## 8. Dead code

`AnswerGenerator.generate()` and `SYSTEM_PROMPT` were unused. `PdfViewer.tsx`
was imported by nobody and duplicated `pdfUrl()`. `submitFeedback()` and
`checkHealth()` were exported and never called, the endpoint working with no UI
behind it. `IngestionProgress.stale_documents` was computed and logged and
absent from the response model.

Closed by #16, all four. `/api/health` stayed, because the Kubernetes liveness,
readiness and startup probes read it; only the unused frontend client went.

Wiring the feedback UI found something the notes had missed. The endpoint had
never worked outside a container: `feedback_file` and `documents_dir` both
defaulted to paths under `/data/`, which does not exist on a developer machine,
so the first POST answered 500 on `mkdir`. No feedback had ever been recorded
anywhere.

Bringing `stale_documents` into the response model revealed that the detection
behind it had never run in the steady state, which became #45.

## 9. Small items

Imports inside function bodies: `FileResponse` and `datetime` in `routes.py`,
`Path` in `_run_ingestion_inner`. Missing annotations on
`_extract_furniture_text(doc)` and on the `metadata` parameter of
`_store_doc_record`. Two `OpenAI()` clients, of which embeddings had
`timeout=60.0` and the generator had none, so a hanging call would block
forever.

Closed by #65, with one correction. Blocking forever is wrong: the openai
client applies its own default of 600 seconds for reads when none is given, so
generation was bounded at ten minutes rather than unbounded. That is still the
wrong number for a request somebody is watching a spinner for, and the frontend
sets no timeout of its own, so the browser waits exactly as long as the backend
does. Both clients now take their timeout from settings, 60 seconds for
embedding and 120 for generation, each measured against the live hub rather
than picked. Embedding one query takes about 0.2 seconds; an answer or an
overview takes 20 to 29 seconds across six samples.

The annotations arrived with `disallow_untyped_defs`, which is the durable part
of that change. An unannotated parameter is silently `Any`, so mypy checked
nothing about it and reported nothing either, which is how two of these sat
unannotated since before `domain/` existed to name their types. Turning the
setting on cost four annotations across 22 modules.

## 10. Tooling

`ruff` was a dev dependency with no `[tool.ruff]` section. `.mypy_cache/` was
committed, with no mypy configuration and no gitignore entry. `numpy` and
`pypdfium2` were imported directly while present only transitively through
docling. No CI ran the tests, although the offline tier was roughly 100 tests
and a 30 second job. Ports were inconsistent four ways: 3000 and 8000 in the
README, 5173 and 8001 in compose, 3000 and 5173 in CORS, 8001 in the vite
proxy. Four env files existed, of which compose used only the root one while
`conftest.py` read the backend one.

Closed by #10 for ruff and mypy, #12 for CI, #13 for the two direct
dependencies, and #15 for the ports and env files. Two counts here have since
gone stale rather than wrong: CI has run the offline tier since #12, and that
tier was 287 tests at the time rather than roughly 100. The env files collapsed
to one, `backend/.env`, read by compose, local runs and the tests alike.

## 11. ExplorerView.tsx at 731 lines

It held autocomplete, the filter bar, the prompt dialog, the submode tables,
both prompts and the search orchestration.

Closed by #53. The file is 328 lines and nothing in the new `explorer/` folder
exceeds 120. Two of the seven new files are moves and the rest extractions,
which is worth separating: a move cannot change behaviour and an extraction
can. The search area stayed where it was, because pulling it out required
fifteen props, which is the sign of a seam in the wrong place.

The follow-up in #63 covered the extracted components, which is what the split
made possible: vitest and testing-library, 26 tests, run by CI. Writing them
found that the filter triggers had no accessible name, and that their
`placeholder` props can never display because the value is never empty.

## 12. Ingestion state singleton

`_progress` is a module global that `run_ingestion` rebinds through `global`.
Anything holding the object returned by `get_ingestion_progress()` sees the old
one. It does not survive two replicas.

Open, deliberately. The diagnosis is unchanged and correct.

Fixing it properly means moving that state out of the process, which is a
decision about what SENTRA runs on rather than a leftover of this refactor. #51
took the orchestration out of the request handler and put the job object on
`app.state`, partly so that there is somewhere for this state to go when
somebody takes it on. The mutual exclusion it added is honest about being
single-process.

## 13. Repository layout for production

The numeric prefixes encoded four different kinds of thing: `00_aisc` for
branding, `01` and `02` for deployables, `03_data` for input data, and
`04_experiments` for scratch work. Nothing indicated what shipped.

The original proposal was names rather than numbers:

```text
sentra/  web/                        ship
infra/  docs/  notebooks/  brand/    do not
```

This was superseded by #55. Both `sentra/` and `web/` were considered and
rejected: `sentra/src/sentra` reads badly, and the repository is already called
sentra, so naming one subfolder after it implies the other is not part of it.
`backend` and `frontend` are legible to whoever inherits the repository without
being told. What was built:

```text
backend/  frontend/  k8s/  docker-compose.yml    ship
data/  docs/  notebooks/  brand/                 do not
```

### 13.2 Boundaries were fiction

The important part of this section. `rag/store.py:20` imported `Chunk` from
`sentra.ingestion.chunker`, so storage knew about the chunker.
`services/explorer.py:13` imported five DTOs from `sentra.api.models`, so a
service depended on the HTTP layer. `api/routes.py:72` spawned the ingestion
thread inside the request handler.

The root cause was the absence of a `domain/` package, so types parked wherever
they were first needed. Fixing it was a prerequisite for section 1 and for the
evaluation work. The intended end state was import-linter contracts in CI.

Closed by #18 for both inverted imports and `domain/`, #21 for the contracts,
and #51 for the job. The contract as built reads
`main -> api -> services -> {rag | ingestion} -> (evaluation) -> domain ->
config`, and it runs in pre-commit rather than only in CI. `rag` and
`ingestion` are siblings that may not import each other, which the `|`
delimiter expresses; a `:` would have permitted it, and getting that backwards
passes silently.

Moving the job also closed a race the notes had not spotted. The handler read
the progress status, decided nothing was running, and spawned a thread, with
nothing holding those two steps together and the status only being set from
inside the new thread. Two requests arriving together both started a run,
reproducible about one attempt in three.

### 13.3 Evaluation under a monolith

The plan was one application with an `evaluation` module, where judge
independence came from a settings block, a boot assertion and a test rather
than from process isolation, and the runner still went over HTTP.

Outstanding at the time of writing. The layering contract already reserves an
optional `(evaluation)` layer just above `domain`, so the module has somewhere
to land without a contract change.

### 13.4 Data out of the repository

17 PDFs were tracked in git, with a `./03_data:/data` bind mount, and
`GROUND_TRUTH` in `conftest.py` keyed to those exact filenames.

Closed by #28, which moved the fixture corpus to
`backend/tests/fixtures/corpus`, #29, which stopped tracking the data folder,
and #33, which gave the integration tier its own collection so that it never
reads whatever the operator has ingested. The bind mount is now `./data:/data`.

### 13.5 Infrastructure blockers

Qdrant published 6333 and 6334 to the host with an unauthenticated dashboard.
`depends_on: service_started` combined with a lifespan calling
`ensure_collection()` produced a cold-start race that wanted a healthcheck and
`service_healthy`. There was one compose file with development bind mounts
baked in, and no image build or smoke test in CI.

Partly closed. #30 pinned the server image and matched the client version,
after finding the server, the client floor and the manifest all disagreeing.
The README now records that the dashboard is unauthenticated and its ports
published. The cold-start race, the single compose file and the missing image
smoke test remain open.

### 13.6 Migration order

Each step was meant to leave the repository green.

```text
1 docs/ and brand/          no code references
2 compose split             ports and healthcheck land here
3 domain/ and the two inverted imports
4 import-linter contracts
5 02_backend to sentra, 01_frontend to web
     touches compose contexts, two Dockerfiles, conftest parents[2],
     documents_dir, README
6 tests/unit and tests/integration, trim the fixture corpus
7 04_experiments to notebooks/, optional dependency group
8 fold in the evaluation module
```

Steps 1, 3, 4, 5 and 7 are done. Step 6 was done differently. Steps 2 and 8
remain open.

The order held. Doing 3 and 4 before the rename was right, and by the time #55
ran, the prediction about what step 5 would touch was accurate except for the
Dockerfiles, which needed nothing because both use only paths relative to their
build context. Step 6 became markers rather than directories, which keeps one
conftest and one fixture set.

## 14. Found while doing the above

None of these appeared in the original notes. They are what the work actually
turned up, which is the argument for reading code rather than only planning
against it.

### Fixed

- The feedback endpoint had never worked outside a container, so no feedback
  had ever been recorded (#16).
- Stale-document detection had never run in the steady state. It sat below a
  return that fires whenever every file is already indexed, having been added
  two months after that return, so it was born unreachable on the common path.
  The live index held 17 orphans and reported none (#45).
- Two concurrent ingest requests could both start a run (#51).
- A Qdrant blip between the skip-filter lookup and `ensure_collection` made
  ingestion reparse and re-embed the whole corpus, and report success (#61).
- A filename containing a double space produced a malformed Aktenzeichen,
  which then cost the document its Fachbereich name (#41).
- `npx tsc --noEmit` checks nothing in this repository. The root tsconfig uses
  project references with `"files": []`, so it exits 0 without reading any
  code. `tsc -b` is the working form, recorded in the README (#57).

### Open

- 17 documents are indexed with no file on disk and nothing deletes them. Every
  ingestion run now reports them. A delete path belongs to the source
  management work.
- `pre-commit run --all-files` works from `git ls-files`, so a new file that is
  still untracked is invisible to every hook. Running `git add` first is the
  workaround. This is how #37 merged carrying an unused import.
- `useExplorerSearch` is untested. It owns the five-way endpoint dispatch and
  is the most valuable thing left to cover. It needs the API module mocked.
- The 16 `npm audit` findings in the frontend predate all of this work.
