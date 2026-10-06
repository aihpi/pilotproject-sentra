# Source management notes

The corpus is consumed by two things at once: SENTRA's search, and the
evaluation cases that reference documents by name. Both break in the same ways
when the corpus cannot be described, so they are treated here as one problem.

## Size of the corpus

```text
1919  PDFs under data/, 592 MB
  17  indexed
```

The earlier count was 1966 files at 618 MB under `03_data`, before the tree was
flattened into a single directory and the folder was renamed in #55.

`glob("*.pdf")` is not recursive and is pointed at `data/Ausarbeitungen`. Under
the old tree, roughly 1950 files under `Extra/ab_2023/` were invisible to it.
Flattening the corpus by hand removed that particular gap, but the glob is
still not recursive, so the gap returns the moment anyone adds a subdirectory.

The problem this states is not that an upload button is missing. It is that one
percent of a real corpus is indexed and there is no mechanism for the rest.

## Measured failures

| Fact | Consequence |
|---|---|
| 30 duplicate filenames across folders | A filename is not unique, so it cannot be an identity |
| 65 joint documents such as `WD 1-019-24; WD 7-060-24.pdf` | They contain 133 Aktenzeichen. `_FILENAME_RE.search()` keeps 65, so 68 are dropped without a trace |
| 105 of 1966 filenames do not match the Aktenzeichen pattern | `AB 05-24.pdf` and `EU-05-25.pdf` belong to a different naming genre |
| `Ausarbeitungen/PE 6/` holds `EU 6-*` files | The folder does not agree with the Aktenzeichen prefix, so paths are not a metadata source either |
| `WD 8 ab 01.01.2024` and `bis 31.12.2023` | An organisational change encoded in a path |
| `FACHBEREICH_NAMES` has 11 entries, the tree has 12 units | PE 6 is missing |
| `list_documents` deduplicates by Aktenzeichen | Documents without one collapse into a single row, and failed documents are invisible |
| No per-document delete exists; `store.py` offers only whole-collection removal | Deleting a PDF leaves its chunks searchable and citable indefinitely |
| Stale documents are computed during ingestion and only logged | The drift is already detected and never surfaced |
| 23 `.docx` files sit alongside the PDFs, and both globs are `*.pdf` | They are skipped silently, although Docling accepts the format |

## The abstracts in .docx, and why they stay out

Twenty-three `.docx` files sit next to the PDFs and are skipped, because
`parse_pdfs` and the pre-filter in `ingest.py` both glob `*.pdf`.
`DocumentConverter()` accepts docx with no configuration, so the parser is not
the obstacle.

What they are:

- 22 of 23 are named `*_Abstract.docx` or `* Abstract.docx`
- 21 of 23 have their parent PDF already in the corpus, sharing its
  Aktenzeichen
- one is standalone, `AB Europa Franz-Ratspräsidentschaft - RED final.docx`

The storage layer was prepared for these and the ingestion layer never was.
`store.py` names `_Abstract` pairs in three separate comments, and commit
`a913c3f` re-keyed Qdrant points by `source_file` precisely because an abstract
and its parent share an Aktenzeichen. Someone met the collision, fixed
identity, and left the glob alone.

They remain excluded because widening the glob settles a question that has not
been settled. `/api/documents` deduplicates by source file, so an abstract and
its parent are two rows. `/explorer/documents` deduplicates by Aktenzeichen, so
the same pair is one row. The Dokumente tab and the search results would
disagree about how many documents exist. Retrieval would also put a short
abstract in competition with the full document it summarises, for the same
query. `DOCUMENT_TYPES` has no entry for an abstract, so all 22 would be
extracted as `Sonstiges`.

The decision belongs with the registry work below, where a document can hold a
relationship to another document rather than merely colliding with it.

## Document registry

Postgres, with Qdrant reduced to a derived index.

```text
documents(id uuid pk, content_hash sha256 uniq, storage_key, original_name,
          status[pending|needs_review|indexed|failed|withdrawn],
          source[upload|folder_import],
          extracted jsonb, provided jsonb, overrides jsonb,
          chunk_count, index_version, indexed_at, created_by, created_at,
          superseded_by)

document_aktenzeichen(document_id, aktenzeichen idx, is_primary)
```

The second table is a separate table rather than a column because joint
documents carry several Aktenzeichen.

Point identity moves from `uuid5(az::chunk_idx)` to
`uuid5(document_id::chunk_idx)`, which makes delete-by-document possible before
an upsert and closes the orphaned-chunk problem at the same time.

### Implementation status

The registry exists. `0001_document_registry` creates `documents`,
`document_aktenzeichen` and `document_files`, and `documents/registry.py`
provides `scan`, `register_file`, `hash_file`, `walk` and `drift`. Ingestion
registers every document before writing its chunks, and point identity is keyed
by document id rather than filename, which is what #188 changed.

Uploads, the metadata layers, the review queue and the delete paths described
below are not built.

## Metadata in three layers

JSON is transport here, not storage.

```text
overrides  entered by a person, in the application
  beats provided   arrived alongside the file
  beats extracted  guessed by metadata.py
```

The precedence applies per field, and no layer destroys the one beneath it.

Two import shapes cover the realistic cases. A per-file sidecar, `X.pdf`
accompanied by `X.json`, suits one-off additions. A single JSONL or CSV
manifest suits bulk, giving 1966 rows one diff and one validation pass.
`yaml.safe_load` reads JSON, JSON being a subset of YAML, so accepting both
formats costs nothing.

A sidecar carries `schema_version`, `aktenzeichen` as a list, `title`,
`fachbereich_number`, `document_type`, `completion_date` in ISO form,
`language`, and optionally `canonical_url`, `supersedes` and `content_sha256`.
It does not carry `status`, `chunk_count`, `index_version` or `indexed_at`,
which are registry state rather than properties of the document.

Failure modes worth deciding in advance: a sidecar with no PDF warns; a PDF
with no sidecar is extracted and may land in `needs_review`; re-importing
updates the provided layer only; a changed PDF whose sidecar did not change is
flagged; and a sidecar that disagrees with extraction is surfaced rather than
silently resolved.

The payoff is measurement. Comparing extraction against provided values gives
per-field accuracy for `metadata.py`, which is untestable today. The
`GROUND_TRUTH` table in `conftest.py` is this same idea, hand-maintained, for
17 files.

Everything here hinges on one unanswered question: can WD export metadata in
machine-readable form? If yes, the manifest becomes the main path and
extraction becomes a validated fallback. If no, 1966 hand-written sidecars will
not happen, and the scope narrows to the roughly 170 files where extraction
fails, being the 105 odd names and the 65 joint documents. The mechanism is the
same either way; only the build order changes.

## Adding documents

Upload sniffs magic bytes rather than trusting the extension, hashes the
content, rejects a duplicate hash, writes to a content-addressed store, and
creates the row as `pending`.

Folder import is recursive and idempotent by hash.

A document whose extraction fails, or that carries several Aktenzeichen, or
that yields `Unbekannter Titel`, becomes `needs_review` and is not indexed.

Storage goes to a named volume behind an opaque `storage_key`, so moving to
MinIO or S3 later is a configuration change. `data/` becomes a read-only seed
and `./data:/data` stops being load-bearing.

## Editing is two operations

They should not be conflated.

A metadata correction writes the overrides layer and rewrites the Qdrant
payloads through `set_payload`. Nothing is re-embedded, because none of those
fields appear in the embedded text.

Normalising instead was considered and does not work. `fachbereich_number`,
`document_type` and `language` have payload indexes and drive filtering in
`store.search`. Moving them out of the payload either breaks filtering or turns
it into a large identifier allowlist. They stay denormalised, and the payload
remains a projection of the registry.

A file replacement keeps the row, increments `index_version`, deletes the
chunks by document id, and reparses, rechunks and re-embeds in full. This takes
minutes. The old blob is retained, because past evaluation runs cited it.

## Deleting is two operations

Withdrawal is the default. Status becomes `withdrawn` and the chunks are
removed from Qdrant, while the row and the blob are kept. The system can still
answer whether a document was in the corpus when a given answer was generated,
and the action is reversible.

Purging removes the row and the blob. It needs a confirmation, a role, and a
reference check: evaluation cases name documents as `referenz_korrekt` or
`referenz_falsch`, so purging one silently invalidates a case.

Purging needs explicit sign-off before it is built. Deletion means different
things to a developer and to an archivist.

## Versioning

The evaluation method requires it. Vorlage 4.3b sets a deliberate trap: each
case has a correct source and a topically similar outdated one. That only works
if the corpus holds both and knows which is which, which is what
`superseded_by` records. Superseded documents stay indexed on purpose, flagged
as such.

## Reconciliation

Folder import is idempotent by hash and can be run at any time.

Drift is checked in both directions: documents marked indexed with no points,
and points with no registry row. Each needs a repair action rather than only a
report.

Mutations are locked while an evaluation round is in flight, in the same shape
as the existing 409 on ingest.

## Scale

Estimates rather than measurements.

| Area | Estimate |
|---|---|
| Parsing | Docling takes 5 to 20 seconds per PDF. At 1966 documents that is hours, plausibly overnight. Today this is one daemon thread and one global |
| Embedding | Roughly 25 chunks per document gives about 50,000 chunks, or about 1500 batches at `embedding_batch_size=32` |
| Memory | 50,000 by 4096 at f32 is about 800 MB of raw vectors, and the chunk text sits in the payload, so Qdrant holds the whole corpus. The default keeps vectors in RAM, so on-disk storage or quantization becomes necessary |
| `scroll_all_documents` | Pages at `limit=100`, which is 500 round trips per page load at 50,000 points |

The conclusion is per-document job rows, a real queue, and resumable runs. This
is the same machinery the evaluation runner needs.

## Proposed API

```text
GET    /api/documents              registry-backed, filtered, paginated
POST   /api/documents              upload, creating a pending row
POST   /api/documents/import       recursive scan, idempotent
GET    /api/documents/{id}         extracted, provided, overrides, status
GET    /api/documents/{id}/file    inline PDF
PATCH  /api/documents/{id}         overrides, followed by a payload rewrite
PUT    /api/documents/{id}/file    replacement, followed by a full reindex
POST   /api/documents/{id}/reindex
POST   /api/documents/{id}/withdraw
DELETE /api/documents/{id}         purge, guarded
GET    /api/documents/drift
GET    /api/documents/jobs
```

This breaks `GET /api/documents/{filename}`, which becomes `{id}/file`. It
touches `pdfUrl()` and every source card in `GeneratedAnswer.tsx`, and it
removes the user-controlled path join that `serve_document` currently has to
guard.

## Frontend

`DocumentsView` becomes real management: drag-and-drop upload, a status column,
the `needs_review` filter as the primary view, row actions for edit, replace,
reindex and withdraw, an inline PDF preview so a document can be seen before it
is approved, and a drift panel.

A `PdfViewer.tsx` modal existed, went unused from the day it was written, and
was removed during the dead-code work. It duplicated `pdfUrl()` with its own
base URL, and a review screen wants a viewer shaped for its own layout rather
than a modal. The 39 lines are at
`git show 9bb439e:01_frontend/src/components/PdfViewer.tsx`, under the pre-#55
path, if they are worth starting from.

`DocumentsTable` needs server-side pagination and search at 1966 rows.

## Open questions

What deletion means here. This is a records question rather than a technical
one.

Who may add or withdraw documents, which is the same unresolved authorisation
question that `SECURITY_NOTES.md` parks.

Whether to ingest all 1966 at once or in stages by Fachbereich, with an
evaluation round after each stage.

PE 6, the 105 odd names and the joint documents are all prerequisites for a
clean bulk import.

Whether the `Aktueller Begriff` genre needs its own `document_type`, given its
different length, and whether it belongs in the same collection.

Retention: whether every replaced blob is kept.

Whether WD can export metadata, which decides manifest-first against
review-queue-first.

Ownership of the sidecar schema. `schema_version` should be agreed before the
first import.

Evaluation cases should reference a document id and display the Aktenzeichen.
Otherwise correcting an Aktenzeichen breaks a case silently.

## Build order

```text
1  registry and recursive folder import, read only: 1966 rows, nothing indexed
2  GET /api/documents from the registry; point ids by document id; delete before upsert
3  job queue, per-document status, resumable
4  sidecar and manifest import into the provided layer; extraction-vs-provided diff report
5  overrides and the needs_review queue
6  upload, replace, withdraw
7  purge with reference checks
8  drift panel and repair
9  staged bulk ingest by Fachbereich, after configuring Qdrant memory
```

Steps 1 and 2 have been built. Step 1 was worth doing before committing to the
rest, because it tells more about this corpus than further design would.
