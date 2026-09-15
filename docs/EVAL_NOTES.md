# Eval harness notes

Implements `Vorlage_Strukturierte_Testverfahren_KISZ.md` v0.3, in this folder.

## Shape

- modular monolith. `sentra.evaluation`, own router at `/api/eval`
- import path identical before/after the repo rename → not blocked on it
- runner → SENTRA over **HTTP** at `SENTRA_BASE_URL` (defaults to self). never in-process: API layer is under test
- Postgres for eval data. SENTRA must still boot without it → `EVAL_ENABLED`, lazy session, 503 from eval routes
- judge = different model. boot assert `JUDGE_MODEL != CHAT_MODEL` + import-linter: `evaluation` ⊄ `generation`
- frontend = third view, same origin, nginx unchanged

## Free from the current design

- no session state anywhere → 4.1 "3 getrennte Sitzungen" = 3 POSTs in a loop
- `system_prompt` echoed back, incl. on the no-results path → provenance per call, no side table
- `sources[]` keyed by Aktenzeichen → **4.3b = set comparison, zero backend changes**. cheapest real check

## Traps (all verified in code)

| trap | consequence |
|---|---|
| `answer` uses `top_k` raw (10); `documents` uses `top_k*3` + `_aggregate_docs` | missing source usually = chunk rank 11, not retrieval failure → measure recall via `/explorer/documents` |
| `[n]` markers are unenforced convention, model counts itself | check marker↔source alignment mechanically |
| `store.search` swallows bad year, drops date filter | typo silently unfilters a case → validate filters, dropdowns not free text |
| `Kurzinformation` / <1000 chars = single chunk | one shot at retrieval, different `top_k` behaviour |
| `_complete` discards `finish_reason`; Überblick 3072 vs Fachfrage 2048 | truncation reads as inconsistency → severity findings against a token ceiling |
| point ids `uuid5(az::idx)`, no delete before upsert | re-chunk to fewer pieces = orphan points, still searchable |

## 4.3a is blocked

`format_context()` gives the model exactly: `[Quelle: <AZ>, Abschnitt: <section_title>]` + chunk text.
No page, no paragraph, no offset. Docling knows the page, chunker discards it.
→ model **cannot** cite finer than a section. Not a prompt problem.

Decision needed: WD accepts section-level verification, OR provenance through the chunker + full re-ingest.

## Cases

- immutable versions. expected answer + both reference fields lock on first run
- Test-ID backend-allocated, never reused → DB constraint, not discipline
- variants proposed once, approved, **frozen into the version**. never generated per run
- yaml import/export both directions → git authoring still possible
- audit property: expected answer provably predates the run

## Checks — deterministic, no LLM

| check | Vorlage |
|---|---|
| source set diff: `referenz_korrekt` present? `referenz_falsch` present? | 4.3b |
| marker alignment: every `[n]` has an nth source, every source cited | 4.3a partial |
| refusal: exact `"Es wurden keine relevanten Dokumente gefunden."` + `sources: []` | 4.4 |
| retrieval recall: expected AZ present, at what rank | new |
| byte dupe: 2 of 3 repeats identical (temp 0.1) | 4.1 shortcut |
| truncation | new |

## Judge

Only 4.1 + 4.2. Reason: those compare *between* samples, scripts can't.
Question is always: Kernaussage / Zahlen / Quellen differ? Never wording.
Output structured `{verdict, dimension, begruendung}`. Prose can't be aggregated.

## ragas

- covers ~1 of 6 checks (4.3c ≈ faithfulness). adds context precision/recall, answer correctness vs `erwartete_antwort`
- **cannot** do 4.1, 4.2 (single-sample metrics), 4.3a, 4.3b, or any process
- caveat: faithfulness = grounded in ANY retrieved context. 4.3c = supported by THE CITED source. claim from chunk 5 cited as `[2]` passes faithfulness, fails 4.3c
- use inside `checks/`, map score+threshold → verdict. **reviewer never sees 0.72**
- needs `retrieved_contexts` → same debug-flag dependency
- don't let its dataset object become our data model. don't use synthetic testset generation to replace Phase 1
- adjacent: langfuse overlaps run storage + annotation queue (self-hostable); promptfoo ≈ 4.2; deepeval ≈ CI

## Triage

```
grenzfall                → review, always, no filtering
check failed             → review
judge auffällig          → review
clean → pool → seeded 10% → review, tagged Stufe 3
```
Seed stored on the run.

## Review screen

- left: answer + source cards (reuse `GeneratedAnswer.tsx`) → inline PDF for 4.3c.
  the old `PdfViewer.tsx` modal was deleted as dead code; it duplicated `pdfUrl()`
  and a review screen wants a viewer shaped for its layout. recoverable from
  `git show 9bb439e:01_frontend/src/components/PdfViewer.tsx`
- right: the case, read only, the yardstick
- tabs: 3 repeats + 3 variants
- bottom: verdict form. 4.3a/b prefilled, 4.3c human only, Schweregrad, Reproduzierbar, Freitext
- **judge verdict hidden until submit.** else the Stufe1-vs-human KPI measures anchoring
- human never overwrites machine. both rows kept forever
- Schweregrad 3/4 → KISZ escalation flag at submit

## Asks on SENTRA

1. `debug: true` → raw hits. already in `_generate` as `results`. **gates most of 4.3**
2. `finish_reason` / `truncated`
3. model id from the hub, per response
4. `GET /api/prompts` (frontend has the same copy-paste problem)
5. delete-by-document before upsert
6. page provenance through the chunker — only if WD requires it, expensive
7. wire up `/api/feedback` → "Testfall aus Feedback erstellen"

## Open

- section vs page citations → blocks 4.3a
- auth: none exists today, verdicts need an author
- Postgres vs SQLite
- eval dependency group in the prod image?
- `domain/` first — yes, prerequisite, else we repeat the `explorer.py` coupling
- ~180 generation calls/round + judge + ragas → check hub quota before promising weekly
- German UI and reports, English code

## Order

```
0  domain/ + fix backwards imports        (restructure feature, prerequisite)
1  module skeleton, judge assert, PG behind flag, case store, yaml import
2  runner + stored calls, no checks
3  review screen                          ← hours live here
4  source set diff + retrieval recall     ← best value/LOC, no backend changes
5  debug flag → marker + quote checks
6  judge for 4.1/4.2 + reveal-after-submit
7  triage, seeded sample, KISZ escalation
8  aggregation + trend report
```
1–3 = milestone: a round can be run and reviewed with zero automation.
