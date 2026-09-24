# Testing notes

How SENTRA is tested and why it is arranged this way: what to run before
pushing, where a new test belongs, and which existing tests will object to a
given change.

`README.md` carries the commands. This carries the reasoning.

## Three suites

One per distribution.

| Suite | Location | Runner | Offline | Integration |
|---|---|---|---|---|
| Backend | `backend/tests/` | pytest | 535 | 85 |
| Evaluation harness | `evaluation/tests/` | pytest | 321 | 10 |
| Frontend | `frontend/src/**/*.test.tsx` | vitest and Testing Library | 119 | none |

Counts taken on 2026-09-24 from `dev` at `7add384`. They go out of date, and
`README.md` and `backend/README.md` both carry older figures. Recompute rather
than trust any of them:

```bash
cd backend && uv run pytest --collect-only -q | tail -1
```

The harness is a separate distribution deliberately. It measures SENTRA, so it
owns no part of it: separate `pyproject.toml`, separate image, separate
database, and it reaches SENTRA over HTTP because SENTRA's API layer is part of
what it is testing. `backend/tests/test_no_evaluation_coupling.py` asserts that
SENTRA does not import it, serve its routes, or carry its settings. That
assertion lives on SENTRA's side because the harness has no dependency on
`sentra` to assert it with, which is the point being defended.

## Two tiers

The split is the `integration` marker.

Offline tests carry no marker and need nothing running: no Qdrant, no AI Hub,
no Postgres, no `.env`. This is the tier CI runs and the one to run before
pushing.

Integration tests carry `@pytest.mark.integration` and need real services. For
the backend they also need an index built from the fixture corpus.

```bash
cd backend
uv run pytest -m "not integration"    # the tier CI runs
uv run pytest -m integration          # needs Qdrant and the AI Hub
uv run pytest                         # both
```

### Why the integration tier is not in CI

Cost rather than difficulty. Every run embeds live queries and calls the chat
model against the AI Hub, and it needs a real `.env` with real credentials.

This leaves a gap rather than closing one. 85 backend tests run on no pull
request. Anyone changing retrieval, chunking or generation should run the tier
locally, because CI will not catch them.

### The fixture corpus

The backend integration tier runs against an index of its own, built from 17
PDFs in `backend/tests/fixtures/corpus`. It does not read whatever the
developer has ingested, and it writes to `sentra_test_chunks` and
`sentra_test_docs` rather than the real collections.

```bash
cd backend
uv run python -m tests.prepare_index   # a few minutes, 17 documents
uv run pytest -m integration
```

Ground-truth metadata for those files, covering Aktenzeichen, Fachbereich and
dates, is keyed to their exact filenames in `tests/conftest.py`. Renaming a
fixture PDF breaks assertions in a way that looks like a parser defect.

The corpus is versioned with the tests rather than living in `data/`, which is
gitignored. The real corpus is hundreds of megabytes and differs between
machines, and tests cannot assert against something that varies.

### Running the offline tier without credentials

`ai_hub_base_url` and `ai_hub_api_key` are required and have no defaults, which
is deliberate: a server that boots against a placeholder and fails on the first
search is worse than one that refuses to start. The offline tier inherited that
requirement without needing it, since none of those tests calls the hub. They
want a `Settings` for its collection names and paths.

`tests/conftest.py` therefore fills in placeholders when there is no `.env` and
nothing in the environment, pointing at a host under the reserved `.invalid`
TLD. An offline test that does reach for the hub fails on DNS rather than
quietly finding something real. A genuine `.env` is left alone, since
environment variables outrank it.

## What CI runs

Three jobs in `.github/workflows/ci.yml`, all on `ubuntu-latest`.

| Job | Steps |
|---|---|
| Backend | `uvx pre-commit run --all-files`, then `pytest -m "not integration"` |
| Evaluation harness | its own lint, then `pytest -m "not integration"` |
| Frontend | `npm run lint`, `npm test`, `npm run build` |

The Backend job runs the linters for the whole repository, through pre-commit
rather than by invoking ruff and mypy directly, so that the hook and the
pipeline cannot pin different versions and begin disagreeing.

```bash
uvx pre-commit run --all-files    # ruff, ruff-format, mypy twice, import-linter
```

### The trigger is unfiltered on purpose

`pull_request:` carries no branch filter. The branching model is feature
branches from `dev` and task branches from the feature branch, so a task PR
targets neither `main` nor `dev`. With a base filter, those PRs received no
checks at all. Ten task PRs on the evaluation harness merged that way before
anyone noticed, and the first CI run over any of them was the 7645-line feature
merge.

## Structural tests

Several tests assert properties of the codebase rather than behaviour of the
code. They are the ones most likely to fail on a change that is otherwise
correct, and each exists because the property it defends broke silently once.

| Test | Asserts | Origin |
|---|---|---|
| `test_no_evaluation_coupling.py` | SENTRA does not import, route or configure the harness | Keeps the harness a separate distribution, and proves SENTRA's image does not need its dependencies |
| `test_auth_gate.py` | The exact set of guarded routes, by method and path | Makes adding a guard to a read path a deliberate act rather than a copied decorator. The corpus is published material, so guarding reads protects the wrong thing |
| `test_k8s_configmap_matches_settings.py` | Every `Settings` field appears in the cluster configmap or on a list with a written reason | `REGISTRY_DATABASE_URL` was absent for the whole life of the registry and every ingested file failed. The login settings were absent the same way. Nothing in the configmap was wrong, only missing |
| `import-linter`, contract "Layered architecture" | Higher layers may import lower ones, never the reverse | |
| `test_roles.py` | The frontend and backend role orderings match | Nothing can enforce this across two languages, so it is written down in both and asserted |

When one of these fails, the reason belongs in the discussion before the
assertion is changed. Each carries the story of the failure it prevents.

## Conventions

Test names are sentences about behaviour rather than about methods:
`test_a_path_is_refused_rather_than_truncated`, not `test_safe_name_2`. The
name should say what breaks when it fails.

Docstrings carry the reasoning. A test asserting something non-obvious explains
what went wrong to make it necessary. `test_uploads.py` says why a path-shaped
filename is refused rather than repaired. `test_provenance.py` says why one
assertion had to be inverted rather than adjusted.

Frontend tests are behavioural. Testing Library, queried by role and accessible
name, never by class or test id. Views that reach for the API on mount are
mocked at the module boundary, so `App.test.tsx` is about which tabs a role is
offered rather than about what the tabs contain.

Partial success deserves its own test. Several endpoints report per item rather
than failing the whole request, and the tests that matter are the ones
asserting that the good items survive the bad one.

---

## The tests, file by file

Each description is that file's own module docstring, so a row that reads
oddly means the docstring is what wants fixing. A diamond marks a file
containing integration tests, which CI does not run.

### Backend, in `backend/tests/`

| File | Tests | Covers |
|---|---:|---|
| `test_answer_dispatch.py` | 11 | How the explorer picks which generating method to run |
| ◆ `test_answer_generation.py` | 11 | Answer generation (UC#10 + UC#2) against real indexed data |
| ◆ `test_api_endpoints.py` | 23 | API contract, via FastAPI TestClient |
| `test_auth_gate.py` | 12 | The gate in front of writing and in front of personal data |
| `test_background_job.py` | 5 | One job, one thread, whatever the callers do |
| `test_chunker.py` | 29 | Chunking, and the provenance each chunk carries |
| `test_config_endpoint.py` | 10 | `GET /api/config`: the prompts and filter options the UI used to hardcode |
| `test_config_wiring.py` | 24 | That settings actually reach the code that should honour them |
| `test_date_filter.py` | 15 | A date filter is applied, or the request fails, and is never quietly dropped |
| `test_debug_payload.py` | 14 | What an answer says about itself when asked, and what it does not say otherwise |
| `test_document_identity.py` | 11 | A document is its contents, not its filename |
| `test_document_registry.py` | 20 | The registry, built from a directory and compared against the index |
| `test_error_policy.py` | 16 | What a failed request answers, per dependency |
| `test_explorer_helpers.py` | 19 | The aggregation and source-reference helpers |
| ◆ `test_external_sources.py` | 9 | External sources (UC#6) against real indexed data |
| `test_feedback_endpoint.py` | 6 | Reading feedback back |
| ◆ `test_filters.py` | 15 | Filter correctness against real indexed data |
| `test_incremental_skip.py` | 8 | The skip filter that makes ingestion incremental, and what it costs to get wrong |
| `test_ingestion_e2e.py` | 31 | End-to-end metadata extraction from real PDFs |
| `test_ingestion_job.py` | 10 | Starting the ingestion, and refusing to start a second one |
| `test_k8s_configmap_matches_settings.py` | 3 | Every setting is in the cluster configmap, or listed with a reason |
| `test_login.py` | 23 | The prototype login: sessions, and the three endpoints that manage them |
| `test_metadata.py` | 66 | Metadata extraction from Bundestag documents |
| `test_no_evaluation_coupling.py` | 7 | SENTRA does not know the evaluation harness exists |
| `test_offline_settings.py` | 6 | The offline tier, and only that tier, builds `Settings` without AI Hub credentials |
| ◆ `test_provenance.py` | 12 | Page and paragraph, carried out of the parser instead of thrown away |
| ◆ `test_reingestion.py` | 7 | Re-ingesting a document replaces it, rather than adding to it |
| `test_roles.py` | 18 | What a caller may do, once it is known who they are |
| ◆ `test_search_relevance.py` | 11 | Search relevance against real indexed data |
| ◆ `test_similar_docs.py` | 8 | Similar documents (UC#4) against real indexed data |
| `test_stale_documents.py` | 9 | Documents in Qdrant with no file on disk |
| `test_store_collection.py` | 26 | The shared collection mechanics in the vector store |
| `test_url_extraction.py` | 28 | URL extraction from Docling markdown |
| `test_user_admin.py` | 18 | Administering users, and the two rules that keep an installation usable |

### Evaluation harness, in `evaluation/tests/`

| File | Tests | Covers |
|---|---:|---|
| ◆ `test_ablehnung_live.py` | 5 | 4.4 against the real judge, on the answer that caused the decision |
| `test_a_whole_round.py` | 10 | A round driven the way an operator drives one, end to end |
| `test_cases.py` | 23 | The case store, and the rule the whole harness rests on |
| `test_cases_api.py` | 14 | The case endpoints, over HTTP |
| `test_checks.py` | 46 | 4.3b and retrieval recall, over stored responses |
| `test_database.py` | 10 | The eval database is a dependency of the harness, not of SENTRA |
| `test_feedback.py` | 12 | Turning a complaint into a test case |
| `test_judge.py` | 13 | The judge: the one check that needs a model, and the ways it can lie |
| ◆ `test_migrations.py` | 5 | The schema comes from alembic, and only from alembic |
| `test_ragas_checks.py` | 11 | ragas scores, mapped to verdicts |
| `test_report.py` | 21 | The Phase-4 sheets, and the number the whole process is calibrated by |
| `test_review.py` | 36 | Stufe 2: the queue, and what a human decided |
| `test_runner.py` | 34 | Running a round, and being able to stop in the middle of one |
| `test_sheet_upload.py` | 10 | Uploading a filled collection sheet, over HTTP |
| `test_skeleton.py` | 7 | The harness is its own application, and refuses to run next to itself |
| `test_triage.py` | 12 | Stufe 1's decision: who a human actually has to look at |
| `test_variants.py` | 12 | 4.2: paraphrases proposed by a model, approved by a person |
| `test_vorlagen.py` | 19 | The collection templates, and the round trip through them |
| `test_yaml.py` | 24 | Cases as a file, both directions |

### Frontend, in `frontend/src/`

| File | Tests | Covers |
|---|---:|---|
| `App.test.tsx` | 12 | Signing in, and what each role is offered |
| `components/administration/AdministrationView.test.tsx` | 15 | Administering the test set |
| `components/administration/RoundControls.test.tsx` | 9 | Getting a round going without a terminal |
| `components/administration/UserPane.test.tsx` | 10 | Administering who can sign in |
| `components/evaluation/EvaluationView.test.tsx` | 20 | The review screen, and mostly one property of it |
| `components/evaluation/PdfPane.test.tsx` | 9 | The cited document, beside the claim |
| `components/evaluation/ResultsView.test.tsx` | 13 | What a round concluded, and mostly one property of it |
| `components/explorer/FilterBar.test.tsx` | 9 | The filter bar |
| `components/explorer/PromptDialog.test.tsx` | 9 | The prompt dialog |
| `components/explorer/ResultPanel.test.tsx` | 8 | The result panel |
| `components/explorer/SourceCards.test.tsx` | 5 | The numbered cards under an answer |

Three explorer files carry no module docstring, so their rows above are only
their names. A sentence each saying what property they defend would bring them
into line with the rest of the suite.

Most assertions live in two files, `test_metadata.py` at 66 and
`test_checks.py` at 46. Both are about extracting structure from text that was
written for people to read.

---

## Before you push

```bash
uvx pre-commit run --all-files
cd backend     && uv run pytest -m "not integration" -q
cd evaluation  && uv run pytest -m "not integration" -q
cd frontend    && npm test && npm run build
```

That is what CI does, so a clean run locally means a green pipeline. The one
exception is the integration tier, which CI never runs and which wants running
by hand after any change to retrieval, chunking, ingestion or generation.
