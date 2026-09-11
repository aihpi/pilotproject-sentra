# Source management — short

Full version: `SOURCE_MANAGEMENT.md`. Consumers: SENTRA search + eval cases (same corpus).

## The number

```
1966  PDFs under 03_data,  618 MB
  17  indexed
```
`glob("*.pdf")` is non-recursive, pointed at `03_data/Ausarbeitungen`.
All of `03_data/Extra/ab_2023/` (~1950 files, Fachbereich × year tree) is invisible to it.
→ not "add an upload button", but "1% of a real corpus is indexed and there is no mechanism for the rest".

## What breaks, measured

| fact | consequence |
|---|---|
| 30 duplicate filenames across folders | filename is not unique → cannot be identity |
| 65 joint docs, `WD 1-019-24; WD 7-060-24.pdf` | contain **133 AZ**, `_FILENAME_RE.search()` keeps 65. **68 silently dropped** |
| 105 / 1966 filenames don't match the AZ regex | `AB 05-24.pdf`, `EU-05-25.pdf` = different naming genre |
| `Ausarbeitungen/PE 6/` holds `EU 6-*` files | folder ≠ AZ prefix → paths aren't a metadata source either |
| `WD 8 ab 01.01.2024` / `bis 31.12.2023` | org reorg encoded in a path |
| `FACHBEREICH_NAMES` = 11 entries, tree = 12 units | PE 6 missing |
| `list_documents` → `scroll_all_documents()`, dedupe by `aktenzeichen` | AZ-less docs **all collapse into one row**; failed docs invisible |
| no per-document delete anywhere (`store.py` only has collection nukes) | deleting a PDF leaves chunks searchable + citable forever |
| `stale_documents` computed in `ingest.py`, only logged | drift already detected, never surfaced |

## Core move: document registry

Postgres (already coming for eval). Qdrant becomes **purely derived**.

```
documents(id uuid pk, content_hash sha256 uniq, storage_key, original_name,
          status[pending|needs_review|indexed|failed|withdrawn], source[upload|folder_import],
          extracted jsonb, provided jsonb, overrides jsonb,
          chunk_count, index_version, indexed_at, created_by, created_at, superseded_by)

document_aktenzeichen(document_id, aktenzeichen idx, is_primary)   -- many, joint docs
```

Point ids: `uuid5(az::chunk_idx)` → `uuid5(document_id::chunk_idx)`.
→ enables delete-by-document before upsert → also fixes the orphan-chunk bug.

## Metadata: 3 layers, json is transport not storage

```
overrides  (human, in app)
  beats provided   (arrived with the file)
  beats extracted  (metadata.py guessed)
```
Per **field**. No layer destroys the one below.

- per-file sidecar `X.pdf` + `X.json` → one-off adds
- one jsonl/csv manifest → bulk (1966 rows, one diff, one validation)
- `yaml.safe_load` reads json (json ⊂ yaml) → accept both for free

Sidecar fields: `schema_version`, `aktenzeichen` (**list**), title, fachbereich_number,
document_type, completion_date (ISO), language, + optional `canonical_url`, `supersedes`, `content_sha256`.
**Not** in sidecar: status, chunk_count, index_version, indexed_at (= registry state).

Failure modes: sidecar w/o pdf → warn. pdf w/o sidecar → extract, maybe `needs_review`.
re-import → updates `provided` only. pdf changed + sidecar didn't → flag.
sidecar ≠ extraction → **surface it**, don't silently pick.

**Payoff:** extraction vs provided = per-field accuracy for `metadata.py`. Today untestable.
`conftest.py` `GROUND_TRUTH` is this idea, hand-maintained, for 17 files.

**Hinges on:** can WD export metadata machine-readably?
- yes → manifest is the main path, extraction becomes a validated fallback
- no → 1966 hand-written sidecars won't happen. scope = the ~170 files where extraction fails
  (105 odd names + 65 joint). same mechanism either way, only decides build order.

## Add

- upload: sniff magic bytes (not `.pdf`), hash, reject dup hash, content-addressed store, row = `pending`
- folder import: **recursive**, idempotent by hash
- extraction fails / multiple AZ / `Unbekannter Titel` → `needs_review`, **not indexed**
- storage: named volume, opaque `storage_key` → MinIO/S3 later is a config change
- `03_data` becomes read-only seed, `./03_data:/data` stops being load-bearing

## Edit = 2 operations (do not conflate)

**Metadata correction** → write `overrides` only. Rewrite Qdrant payloads via `set_payload`. **No re-embedding** (none of those fields are in the embedded text).
> Considered normalising instead: doesn't work. `fachbereich_number`, `document_type`, `language` have payload indexes and drive `store.search` filtering. Move them out → filtering breaks or becomes a big id allowlist. Keep denormalized, payload = projection of registry.

**File replacement** → keep row, bump `index_version`, delete chunks by doc id, full reparse/rechunk/re-embed. Minutes. Old blob retained (past eval runs cited it).

## Delete = 2 operations

- **withdraw (default):** status → `withdrawn`, chunks removed from Qdrant, row + blob kept.
  → can still answer "was this in the corpus when that answer was generated". reversible.
- **purge (guarded):** row + blob gone. confirmation + role + reference check.
  eval cases name docs as `referenz_korrekt`/`referenz_falsch` → purging one silently invalidates a case.

⚠ needs explicit sign-off. "delete" means different things to a developer and an archivist.

## Versioning — required by eval

Vorlage 4.3b deliberately traps: each case has a correct source **and** a topically similar outdated one.
Only works if the corpus holds both and knows which is which → `superseded_by`. Superseded docs stay indexed on purpose, flagged.

## Reconciliation

- folder import idempotent by hash, run anytime
- drift check both directions: indexed w/o points, points w/o registry row. + repair action
- mutation lock while an eval round is in flight (same shape as the existing 409 on ingest)

## Scale — estimates, not measurements

| | |
|---|---|
| parsing | Docling 5–20 s/pdf × 1966 → **hours, plausibly overnight**. today = 1 daemon thread + 1 global |
| embedding | ~25 chunks/doc → ~50k chunks → ~1500 batches at `embedding_batch_size=32` |
| memory | 50k × 4096 × f32 ≈ **800 MB raw vectors**, + chunk `text` sits in the payload → Qdrant holds the whole corpus. default keeps vectors in RAM → need on-disk / quantization |
| `scroll_all_documents` | pages at `limit=100` → **500 round trips per page load** at 50k points |

→ per-document job rows, real queue, resumable. Same machinery the eval runner needs.

## API

```
GET    /api/documents              registry-backed, filtered, paginated
POST   /api/documents              upload → pending
POST   /api/documents/import       recursive scan, idempotent
GET    /api/documents/{id}         row: extracted + provided + overrides + status
GET    /api/documents/{id}/file    inline pdf
PATCH  /api/documents/{id}         overrides → payload rewrite
PUT    /api/documents/{id}/file    replace → full reindex
POST   /api/documents/{id}/reindex
POST   /api/documents/{id}/withdraw
DELETE /api/documents/{id}         purge, guarded
GET    /api/documents/drift
GET    /api/documents/jobs
```
**Breaking:** `GET /api/documents/{filename}` → `{id}/file`. Touches `pdfUrl()` + every source card in `GeneratedAnswer.tsx`. Removes the user-controlled path join `serve_document` currently guards.

## Frontend

`DocumentsView` → real management. drag-drop upload · status column · **`needs_review` filter as the primary view** ·
row actions (edit / replace / reindex / withdraw) · `PdfViewer.tsx` finally used for preview-before-approve · drift panel.
`DocumentsTable` needs server-side pagination + search at 1966 rows.

## Open

- what does delete mean here (records question, not technical)
- who may add / withdraw → same unresolved auth question as eval
- ingest all 1966? staged by Fachbereich, eval round after each stage
- `PE 6` + 105 odd names + joint docs → all 3 are prerequisites for a clean bulk import
- `Aktueller Begriff` genre: new `document_type`, different length. same collection?
- retention: keep every replaced blob?
- can WD export metadata → decides manifest-first vs review-queue-first
- sidecar schema ownership → agree `schema_version` before the first import
- eval cases should reference `document_id`, display AZ. else correcting an AZ breaks a case silently

## Order

```
1  registry + recursive folder import, READ ONLY. 1966 rows, index nothing   ← day or two, highest info gain
2  GET /api/documents from registry; point ids → document_id; delete before upsert
3  job queue, per-doc status, resumable
4  sidecar + manifest import → provided layer; extraction-vs-provided diff report
5  overrides + needs_review queue
6  upload, replace, withdraw
7  purge + reference checks
8  drift panel + repair
9  staged bulk ingest by Fachbereich (Qdrant memory config first)
```
Do 1 before committing to the rest. It tells us more about this corpus than more design will.
