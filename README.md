<div style="background-color: #ffffff; color: #000000; padding: 10px;">
<img src="00_aisc/img/logo_aisc_bmftr.jpg">
<h1>Sentra – RAG for Wissenschaftliche Dienste</h1>
</div>

A Retrieval-Augmented Generation (RAG) prototype that enables semantic search and question-answering over documents from the Wissenschaftliche Dienste des Deutschen Bundestages.

## Architecture

```
┌──────────┐      ┌──────────┐      ┌──────────┐
│ Frontend │─────▶│ Backend  │─────▶│  Qdrant  │
│ React    │ :3000│ FastAPI  │ :8000│ VectorDB │ :6333
└──────────┘      └──────────┘      └──────────┘
                        │
                   AI Hub API
                  (Embeddings +
                   Generation)
```

- **Frontend** — React + Vite + Tailwind + shadcn/ui
- **Backend** — FastAPI + Docling (PDF parsing) + OpenAI-compatible AI Hub
- **Vector DB** — Qdrant (cosine similarity, 4096-dim embeddings)
- **Models** — Octen-Embedding-8B (embeddings), llama-3-3-70b (generation)

## Prerequisites

- **Docker & Docker Compose** (for Docker setup)
- **Node.js >= 20** and **Python >= 3.12 with [uv](https://docs.astral.sh/uv/)** (for local dev)
- **AI Hub credentials** (base URL + API key)

---

## Option 1: Docker (recommended)

The simplest way to run the full stack.

### 1. Configure environment

```bash
cp 02_backend/.env.example .env
```

Edit `.env` and set your AI Hub credentials:

```
AI_HUB_BASE_URL=https://your-hub-url.example.com/v1
AI_HUB_API_KEY=your-virtual-key-here
```

The rest of the defaults work as-is for Docker.

### 2. Start all services

```bash
docker compose up --build
```

This starts three services:
| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | Search UI |
| Backend | http://localhost:8000 | FastAPI + Swagger docs at `/docs` |
| Qdrant | http://localhost:6333 | Vector DB dashboard |

### 3. Ingest documents

Open the frontend at http://localhost:3000, navigate to **Dokumente**, and click **Dokumente einlesen**. This parses all PDFs in `03_data/Ausarbeitungen/` and indexes them into Qdrant.

Alternatively, via API:

```bash
curl -X POST http://localhost:8000/api/ingest
```

### 4. Search

Go to the **Suche** tab and ask a question in German, e.g.:

> Welche Regelungen gelten für die Immunität von Abgeordneten?

### Stop

```bash
docker compose down
```

To also clear the vector database:

```bash
docker compose down -v
```

---

## Option 2: Local Development (without Docker)

Run each component separately for faster iteration.

### 1. Start Qdrant

You still need Qdrant running. The easiest way is via Docker:

```bash
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest
```

### 2. Backend

```bash
cd 02_backend

# Create and configure environment
cp .env.example .env
# Edit .env — set AI_HUB_BASE_URL, AI_HUB_API_KEY
# Set DOCUMENTS_DIR to the absolute path of your PDFs:
#   DOCUMENTS_DIR=/absolute/path/to/03_data/Ausarbeitungen

# Install dependencies
uv sync

# Run the server
uv run uvicorn sentra.main:app --reload --host 0.0.0.0 --port 8000
```

The backend is now at http://localhost:8000 (Swagger UI at http://localhost:8000/docs).

### 3. Frontend

```bash
cd 01_frontend

# Install dependencies
npm install

# Run dev server
npm run dev
```

The frontend is now at http://localhost:3000 and proxies API calls to the backend at `localhost:8000`.

### 4. Ingest & search

Same as Docker — navigate to **Dokumente** → **Dokumente einlesen**, then switch to **Suche**.

---

## Project Structure

```
├── 00_aisc/              # Branding assets (HPI/AISC logos)
├── 01_frontend/          # React frontend
│   ├── src/
│   │   ├── components/   # UI components
│   │   ├── lib/          # API client, utilities
│   │   └── types/        # TypeScript interfaces
│   └── Dockerfile
├── 02_backend/           # FastAPI backend
│   ├── src/sentra/
│   │   ├── api/          # Routes, request/response models
│   │   ├── ingestion/    # PDF parsing, metadata extraction, chunking
│   │   ├── rag/          # Embeddings, vector store, answer generation
│   │   └── services/     # Ingestion and query orchestration
│   └── Dockerfile
├── 03_data/              # Sample PDF documents
│   └── Ausarbeitungen/
└── docker-compose.yml
```

## API Endpoints

| Method | Endpoint         | Description                             |
| ------ | ---------------- | --------------------------------------- |
| `POST` | `/api/query`     | Ask a question (supports SSE streaming) |
| `POST` | `/api/ingest`    | Parse and index all PDFs                |
| `GET`  | `/api/documents` | List indexed documents                  |
| `GET`  | `/api/health`    | Health check + Qdrant status            |

---

## Acknowledgements

<img src="00_aisc/img/logo_bmftr_de.png" alt="BMFTR" style="width:170px;"/>

The [AI Service Centre Berlin Brandenburg](http://hpi.de/kisz) is funded by the [Federal Ministry of Research, Technology and Space](https://www.bmbf.de/) under the funding code 01IS22092.
