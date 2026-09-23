<div style="background-color: #ffffff; color: #000000; padding: 10px;">
<img src="brand/img/logo_aisc_bmftr.jpg">
<h1>Sentra – RAG for Wissenschaftliche Dienste</h1>
</div>

[![CI](https://github.com/aihpi/pilotproject-sentra/actions/workflows/ci.yml/badge.svg)](https://github.com/aihpi/pilotproject-sentra/actions/workflows/ci.yml)

A Retrieval-Augmented Generation (RAG) prototype for semantic search and question answering over documents of the Wissenschaftliche Dienste des Deutschen Bundestages.

## Architecture

```
┌──────────┐      ┌──────────┐      ┌──────────┐
│ Frontend │─────▶│ Backend  │─────▶│  Qdrant  │
│ React    │ :5173│ FastAPI  │ :8001│ VectorDB │ :6333
└──────────┘      └──────────┘      └──────────┘
                        │
                   AI Hub API
                  (Embeddings +
                   Generation)
```

- **Frontend** — React + Vite + Tailwind + shadcn/ui
- **Backend** — FastAPI + Docling (PDF parsing) + OpenAI-compatible AI Hub
- **Vector DB** — Qdrant, cosine similarity, 4096-dimensional embeddings
- **Models** — Octen-Embedding-8B (embeddings), llama-3-3-70b (generation)

Qdrant holds **two** collections, both written by the same ingestion run:
`bundestag_documents` has one point per chunk and answers search, while
`bundestag_doc_summaries` has one point per document, carrying a mean embedding
used for "find similar documents".

### Ports

One set of numbers, used everywhere. Host ports are what you open in a browser;
container ports are what `nginx.conf`, the Dockerfiles and the Kubernetes
manifests talk to.

| Service | Host | In container | Where the host port comes from |
|---------|------|--------------|-------------------------------|
| Frontend | 5173 | 80 | `docker compose` maps it, and `vite.config.ts` uses the same for `npm run dev` |
| Backend | 8001 | 8000 | `docker compose` maps it; run `uvicorn --port 8001` locally to match |
| Qdrant | 6333 / 6334 | 6333 / 6334 | mapped straight through |

### Timeouts

Both AI Hub calls are bounded, and the numbers were measured rather than
picked: embedding one query takes about 0.2 seconds, and generating an answer
or an overview 20 to 29 seconds. `EMBEDDING_TIMEOUT_SECONDS` defaults to 60
and `GENERATION_TIMEOUT_SECONDS` to 120, roughly four times the slowest
observed. Raise them if your hub is slower; a request that exceeds one comes
back as a 503.

The backend only allows CORS from `http://localhost:5173`, since that is the one
origin that calls it cross-origin. Under `docker compose` nothing does: nginx
proxies `/api` to the backend, so the browser sees a single origin. Override with
`CORS_ORIGINS` if you serve the frontend from somewhere else.

## Prerequisites

- **Docker & Docker Compose** (for the Docker setup)
- **Node.js >= 20** and **Python >= 3.12 with [uv](https://docs.astral.sh/uv/)** (for local development)
- **AI Hub credentials**: a base URL and an API key

---

## Option 1: Docker

The whole stack, including Qdrant.

### 1. Configure

```bash
cp backend/.env.example backend/.env
```

Then set your credentials in `backend/.env`:

```
AI_HUB_BASE_URL=https://your-hub-url.example.com/v1
AI_HUB_API_KEY=your-virtual-key-here
```

`backend/.env` is the only configuration file, shared by Docker, local runs and
the tests. Compose reads it through `env_file` and overrides just the three
values that differ inside a container: `QDRANT_URL`, `DOCUMENTS_DIR` and
`FEEDBACK_FILE`. Everything else comes from that one file, so there is no second
copy to keep in sync. A `.env` at the repository root is **not** read.

### 2. Start

```bash
docker compose up --build
```

| Service | URL | |
|---------|-----|-|
| Frontend | http://localhost:5173 | the UI |
| Backend | http://localhost:8001 | Swagger UI at `/docs` |
| Qdrant | http://localhost:6333/dashboard | vector DB dashboard |

The Qdrant dashboard is unauthenticated and its ports are published to the host.
That is fine on a laptop and is not suitable as-is for a shared machine.

### 3. Ingest documents

Put the PDFs in `data/Ausarbeitungen/`. That directory is not tracked, so a fresh
clone starts empty, and ingestion reads that one directory without recursing into
subdirectories. See [`data/README.md`](data/README.md).

Open the frontend, go to **Dokumente**, and click **Dokumente einlesen**. Or:

```bash
curl -X POST http://localhost:8001/api/ingest
```

Ingestion runs in the background; poll `GET /api/ingest/status` for progress. It
is **incremental**: a document already in the index is skipped, matched by
filename, so re-running it costs nothing. Pass `?force=true` to re-index
everything, which re-embeds every document and spends AI Hub quota accordingly.
Only one run happens at a time; a second request while one is going gets a 409.

The status also reports `stale_documents`, documents that are in the index with
no matching file on disk. Nothing deletes those yet.

### 4. Search

The **Suche** tab has two halves:

- **Dokumente finden** — search by topic, find documents similar to a given one,
  or list the external sources cited across the corpus.
- **Fragen beantworten** — ask a question and get an answer with numbered
  citations, or a structured overview of a topic. Both show the prompt they used
  and let you edit it, and both take a thumbs up or down that is recorded to
  `FEEDBACK_FILE`.

Ask in German, for example:

> Welche Regelungen gelten für die Immunität von Abgeordneten?

### Stop

```bash
docker compose down        # keep the index
docker compose down -v     # also delete the vector database
```

---

## Option 2: Local development

Faster to iterate on, and what the tests run against.

### 1. Qdrant

```bash
docker compose up -d qdrant
```

Use compose rather than a bare `docker run`, so you get the pinned version. The
server image, the `qdrant-client` floor in `backend/pyproject.toml` and the
Kubernetes manifest are kept on one minor version deliberately; a mismatch
between client and server logs an incompatibility warning and can fail in ways
that look like data problems.

### 2. Backend

```bash
cd backend
cp .env.example .env    # then fill in the AI Hub credentials
uv sync --frozen
uv run uvicorn sentra.main:app --reload --port 8001
```

Swagger UI at http://localhost:8001/docs. The example file points
`DOCUMENTS_DIR` at `../data/Ausarbeitungen`, which resolves when you run the
server from `backend/`.

See [`backend/README.md`](backend/README.md) for the test tiers, the linters and
how to build the integration index.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

At http://localhost:5173, calling the backend at `localhost:8001`, which is what
`frontend/.env.development` sets.

### 4. Ingest and search

As above: **Dokumente** → **Dokumente einlesen**, then **Suche**.

---

## Tests and checks

```bash
cd backend
uv run pytest -m "not integration"   # 390 tests, no services needed. This is what CI runs.
uv run pytest -m integration         # 84 tests, needs Qdrant and the AI Hub

cd ../evaluation                     # the harness is its own distribution
uv run pytest -m "not integration"   # 279 tests, no services needed
uv run pytest -m integration         # 5 tests, needs the eval database

cd frontend
npm test                             # 47 component tests in jsdom, no browser needed
npm run build                        # tsc -b, then vite build
npm run lint
```

```bash
uvx pre-commit run --all-files       # ruff, mypy and the layering contract
```

The evaluation harness lives in `evaluation/`, as its own distribution with its
own process and image. It depends on nothing of SENTRA's and reaches it over
HTTP, because SENTRA's API layer is part of what it is testing. Start it with
`docker compose --profile eval up` — a profile, because most people bringing the
stack up are working on SENTRA rather than measuring it. See
`evaluation/README.md`.

"No services needed" includes `backend/.env`. The offline tier calls no AI Hub,
so `tests/conftest.py` fills in placeholder credentials when there is no env
file and none in the environment, pointing at a host that cannot resolve. That
is what lets CI, which has neither, run the suite at all. A real `.env` is left
alone, since environment variables outrank it.

The integration tier is not in CI, and the reason is cost rather than
difficulty: every run embeds live queries and calls the chat model. It needs
`.env` for real. Its four migration tests also want the eval database
(`docker compose up -d eval-db`) and skip with instructions when it is absent. It uses its own index built from
`backend/tests/fixtures/corpus`, so it never reads whatever you have ingested.

The frontend tests are vitest plus testing-library, sharing `vite.config.ts`
so the `@` alias is defined once. They cover the explorer components that take
plain props, and CI runs them next to the linter.

Note that `npx tsc --noEmit` checks **nothing** in this repository: the root
`tsconfig.json` uses project references with `"files": []`, so it exits 0 without
looking at any code. Use `tsc -b`, which is what `npm run build` does.

## Project Structure

```
Ships:

├── frontend/             # React + Vite single-page app
│   ├── src/
│   │   ├── components/   # UI, with the search screen under components/explorer/
│   │   ├── lib/          # API client, utilities
│   │   └── types/        # TypeScript interfaces
│   └── Dockerfile
├── backend/              # FastAPI application
│   ├── src/sentra/
│   │   ├── main.py       # App, lifespan, error handlers
│   │   ├── api/          # Routes, request and response models
│   │   ├── services/     # Ingestion, explorer and job orchestration
│   │   ├── rag/          # Embeddings, vector store, answer generation
│   │   ├── ingestion/    # PDF parsing, metadata extraction, chunking
│   │   ├── domain/       # Framework-free types the layers above share
│   │   └── config.py     # Settings, read from backend/.env
│   ├── tests/
│   └── Dockerfile
├── k8s/                  # Kubernetes manifests
└── docker-compose.yml

Does not ship:

├── data/                 # Document corpus, not tracked. See data/README.md
│   └── Ausarbeitungen/
├── references/           # Design notes, and documents we received
├── docs/                 # Generated documentation (Sphinx/MkDocs)
├── notebooks/            # Exploratory analysis, its own dependencies
└── brand/                # HPI/AISC logos
```

The backend modules are layered, and the layering is enforced rather than
aspirational: `main → api → services → {rag | ingestion} → domain → config`,
with nothing importing upwards and `rag` and `ingestion` not importing each
other. An `import-linter` contract runs in pre-commit, so a violation fails
before it is committed.

## API

All paths are under `/api`. Swagger UI at `/docs` is the authoritative reference.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/config` | Default prompts and filter options the UI needs at start-up |
| `GET` | `/health` | Status, plus Qdrant connectivity and point count |
| `POST` | `/ingest` | Start a background ingestion run. `?force=true` re-indexes everything. 409 if one is already running |
| `GET` | `/ingest/status` | Progress, errors, and stale documents |
| `GET` | `/documents` | Metadata for every indexed document |
| `GET` | `/documents/{filename}` | Serve one source PDF |
| `POST` | `/explorer/documents` | Search documents by topic |
| `POST` | `/explorer/similar` | Documents similar to a given Aktenzeichen |
| `POST` | `/explorer/sources` | External sources cited across the corpus |
| `POST` | `/explorer/answer` | Answer a question, with citations |
| `POST` | `/explorer/overview` | Structured overview of a topic |
| `POST` | `/feedback` | Record a thumbs up or down on an answer |

Error responses follow one policy. A failure of something we depend on, Qdrant or
the AI Hub, is a **503** with a German message; a bad request is a **4xx** saying
why; anything unanticipated is a **500** and is a bug. So an empty result and a
broken dependency are distinguishable, which they were not in earlier versions.

---

## Design notes

These live in `references/`, alongside the documents we received. `docs/` is
reserved for generated documentation and holds no hand-written notes.

`references/REFACTOR_NOTES.md` records what was refactored and why, including
what is deliberately still open. `references/EVAL_NOTES.md` describes the
evaluation harness as built, with the design's reversals marked where the
original was wrong. `references/SOURCE_MANAGEMENT_NOTES.md` is the design for
adding, editing and removing sources, which is being built now.
`references/SECURITY_NOTES.md` records what the prototype login does not cover
and what has to change before SENTRA is used outside a pilot.
`docs/REFACTOR_NOTES.md` records what was refactored and why, including what
is deliberately still open. `docs/EVAL_NOTES.md` describes the evaluation
harness as built, with the design's reversals marked.
`docs/SOURCE_MANAGEMENT_NOTES.md` is the design for adding, editing and
removing sources, which is being built now (#141); its first piece, the
document registry, is below.

## The document registry

What the corpus consists of. Qdrant holds what has been *indexed*, which is not
the same question — and until the registry existed nothing could compare the
two, which is how 17 documents came to be searchable and citable with no file
behind them (#140).

Read-only so far: it observes the corpus and touches neither Qdrant nor the
files. Retrieval does not read it, so a registry database that is down does not
stop SENTRA answering.

```bash
docker compose up -d sentra-db
cd backend
uv run alembic upgrade head                        # its own schema, applied deliberately
uv run python -m sentra.documents.cli scan         # walk the corpus into the registry
uv run python -m sentra.documents.cli drift        # compare it against the index
```

The scan is idempotent by content hash, so running it twice writes nothing. It
does not parse: Docling is 5 to 20 seconds a document against 1919 of them, and
the value here is being runnable now and repeatedly. What it extracts is what
the filename carries, plus what the index already knows.

What the first scan of this corpus found:

| | |
|---|---|
| 1942 files | 1919 PDFs and 23 `.docx`, which every glob in the codebase skips |
| 1938 documents | 4 are filed twice, the same paper under two names |
| 59 with several Aktenzeichen | **64** that the ingestion path drops, because it keeps the first match |
| 92 with none | `AB 01-23.pdf` and its kind, a different naming genre |
| 17 indexed, no file | citable, and the source card 404s |
| 23 rows, no chunks | the `.docx` abstracts, never ingested |

## Acknowledgements

<img src="brand/img/logo_bmftr_de.png" alt="BMFTR" style="width:170px;"/>

The [AI Service Centre Berlin Brandenburg](http://hpi.de/kisz) is funded by the [Federal Ministry of Research, Technology and Space](https://www.bmbf.de/) under the funding code 01IS22092.
