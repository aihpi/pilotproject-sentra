# Fixture corpus

Seventeen Bundestag WD documents, versioned with the tests that assert against
them. `tests/conftest.py` points `DATA_DIR` here and holds a hand-written
`GROUND_TRUTH` table keyed by these exact filenames.

They are deliberately not read from `data/`. That directory holds whatever
corpus the operator has ingested, which is thousands of documents, and
`test_ingestion_e2e.py` parses everything in `DATA_DIR` through Docling in a
module-scoped fixture. Pointed at an operational corpus that takes over an hour
and holds every parsed document in memory at once.

The set is chosen for coverage rather than size:

- all eleven Fachbereiche, WD 1 through WD 10 plus EU 6
- one English document, `WD 2-027-25_EN.pdf`, which exercises language detection
- two joint-Aktenzeichen filenames, which carry two identifiers in one name
- a spread of lengths, from 76 KB to 3.9 MB

Changing this set means updating `GROUND_TRUTH` to match, since it asserts
per-document metadata by filename.
