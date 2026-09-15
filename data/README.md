# Document corpus

The PDFs SENTRA indexes. **Nothing in this directory is tracked** apart from this
file: the contents are operational data, different on every machine, and
currently hundreds of megabytes.

Put the documents you want indexed in a subdirectory here, then point
`DOCUMENTS_DIR` at it. Ingestion reads a single directory and does **not** recurse,
so every PDF has to sit directly inside the one you name.

```
DOCUMENTS_DIR=../data/Ausarbeitungen     # running the backend locally
DOCUMENTS_DIR=/data/Ausarbeitungen          # inside the container, set by compose
```

`docker-compose.yml` bind-mounts this directory to `/data`, so the two settings
above point at the same files. The feedback log is written here too, as
`feedback.jsonl`, for the same reason.

## Only PDFs are ingested

Ingestion globs `*.pdf`. There are also `.docx` files here, mostly abstracts of
documents that are already indexed as PDFs, and they are skipped on purpose.
Docling could read them; the open question is how an abstract and its parent
should relate, since they share an Aktenzeichen. See
`docs/SOURCE_MANAGEMENT_NOTES.md`.

## This is not the test corpus

Tests read `backend/tests/fixtures/corpus`, seventeen documents versioned with
the code. They deliberately do not read this directory: it holds whatever has
been ingested, and a test fixture that parses all of it takes over an hour.
