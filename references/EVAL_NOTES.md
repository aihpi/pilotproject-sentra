# Eval harness notes

Implements `Vorlage_Strukturierte_Testverfahren_KISZ.md` v0.3, in this folder.

Written as a design draft before any of it existed, and rewritten afterwards to
describe what was actually built. Several decisions in the draft were reversed
by evidence; those are marked, because a document that reads as though the
first answer had been right teaches nobody anything.

## Shape

- **its own distribution and process.** `evaluation/`, package `sentra_eval`,
  own pyproject, lockfile, image and uvicorn entrypoint. It depends on nothing
  of SENTRA's.
  > **Reversed.** The draft said "modular monolith, a module with its own
  > router, not a second service", and that is what was built first (#74). The
  > decision changed in #89: something whose job is to measure SENTRA should
  > not share its lifecycle, and a harness that cannot be restarted without
  > restarting the thing it measures is not independent whatever its import
  > graph says. It was cheap to change because the HTTP boundary below was
  > insisted on from the start — the runner, case store, checks and migrations
  > were untouched by the move.
- runner → SENTRA over **HTTP** at `SENTRA_BASE_URL`. Never in process: the API
  layer is under test.
- Postgres for eval data, its own container, a compose profile. `docker compose
  up` is SENTRA alone; `--profile eval up` brings up the harness.
- judge = different model, asserted at harness startup.
- frontend = third view. nginx routes `/api/eval` to the harness, so the browser
  still sees one origin — the draft's "same origin" survived, nginx just gained
  a route.

## Free from the current design

All three held.

- no session state anywhere → 4.1's "3 getrennte Sitzungen" is three POSTs in a
  loop.
- `system_prompt` echoed back, incl. on the no-results path → provenance per
  call, no side table.
- `sources[]` keyed by Aktenzeichen → 4.3b is a set comparison.
  > **With a caveat the draft missed.** The Vorlage's reference-source fields
  > hold human citations — its own example is "GOBT § 35" — while SENTRA cites
  > its own documents. Comparing those two vocabularies compares nothing, so a
  > case carries both: the citation a reviewer reads and the Aktenzeichen the
  > check matches on (#86). Somebody has to look the latter up by hand, and
  > until they do both source checks report "nicht prüfbar".

## Traps

| trap | status |
|---|---|
| `answer` uses `top_k` raw (10); `documents` uses `top_k*3` + `_aggregate_docs` | **live, and measured.** The recall probe exists for it: a source missing from an answer is usually a chunk at rank 11 |
| `[n]` markers are unenforced convention | **checked** (#93). Dangling markers are a finding; uncited sources are evidence only, after the first real round showed every hedging answer flagged |
| `store.search` swallows bad year, drops date filter | **fixed** (#70) |
| `Kurzinformation` / <1000 chars = single chunk | live, unmeasured |
| `_complete` discards `finish_reason` | **fixed** (#91). Truncation is its own check |
| point ids, no delete before upsert | **fixed** (#83). Existing indexes still hold their orphans; a repair pass is a separate decision |

## 4.3a was blocked by the data, and is not any more

`format_context()` used to give the model exactly `[Quelle: <AZ>, Abschnitt:
<section_title>]` plus chunk text. No page, no paragraph, no offset. Docling
knew both and the chunker discarded them — `parse_pdfs` exported to Markdown
and the export does not carry provenance. The model **could not** cite finer
than a section, so there was nothing for a 4.3a check to compare.

**WD expects finer than section level** (2026-09-18), and specifically
**paragraph, with the page as well** (2026-09-19). The question the draft left
open — section-level verification, or provenance through the chunker and a full
re-ingest — was therefore answered with the expensive option, #134, and that is
now built: parser → chunker → Qdrant payload → prompt → UI all carry
`page_from/page_to` and `paragraph_from/paragraph_to`, and a source card opens
the PDF at its page.

The paragraph half turned out to be free rather than extra: a Docling
`TextItem` is a paragraph and carries its own page. 242 of 242 items in a
normal Ausarbeitung have one.

The check exists as of #189 — `seitenangabe`, comparing the pages an answer
names against the pages its retrieved chunks were drawn from. **Two honest
limits:**

- it verifies the *page*, not the paragraph. Comparing a cited paragraph
  against the one a claim came from is a judgement about meaning, which is 4.3c
  and a human's. What this can do is catch a page nobody was shown, which is
  the mechanical half.
- it reports `nicht prüfbar`, not a pass, wherever it cannot read the answer or
  the chunks carry no page. That is the whole corpus until the re-ingest: every
  point indexed before #134 has no page in its payload. **The check is
  therefore implemented and inert.**

Parsing it conservatively mattered more than expected. The first version used
`(?:Seiten?|S\.)` under IGNORECASE, which matches the "s." ending *"Abs."* —
so `Siehe S. 4, Abs. 3`, the exact format this project puts in the prompt, was
read as pages 3 and 4 and flagged as a deviation. German legal prose abbreviates
Absatz constantly, so that was not an edge case, it was most answers. A false
"weicht ab" on a correct citation is worse than a missed one, because it teaches
reviewers to ignore the check.

Marker alignment is not superseded and stays. It checks that the markers in the
answer line up with the sources returned; `seitenangabe` checks that the pages
were ones the model saw. Neither asks whether the cited passage says what the
answer claims, which is the part only a person does — and a reviewer given
"look in section 2.1" could not do it either, where a section runs four pages.
"Page 4, third paragraph" they can, which is the whole reason the anchor had to
be this fine.

## Cases

As drafted, and all of it holds.

- immutable versions; an approved version cannot be edited at all
- Test-ID backend-allocated from a counter, never reused — including for
  withdrawn cases, which `max(number)+1` would not have guaranteed
- variants proposed once, approved by a person, frozen into the version
- yaml import/export both directions, idempotent

## Checks — deterministic, no LLM

| check | Vorlage | status |
|---|---|---|
| source set diff | 4.3b | built (#87) |
| retrieval recall | new | built (#87) |
| marker alignment | 4.3a partial | built (#93) |
| cited page vs retrieved pages | 4.3a | built (#189); `nicht prüfbar` until the re-ingest gives payloads a page |
| refusal | 4.4 | built (#93), judged rather than literal since #109 |
| truncation | new | built (#93) |
| byte dupe: 2 of 3 repeats identical | 4.1 shortcut | built (#93); saves a judge call when repeats match |

**4.4 did not work as the draft assumed, and the decision has been taken
(#109).** The exact refusal string only appears when retrieval returns nothing,
and vector search always returns the top-k however irrelevant. Asked a
deliberately absurd question, SENTRA retrieved ten unrelated chunks and
answered *"Die Frage kann nicht ausreichend beantwortet werden, da der Kontext
keine Informationen über … enthält"*. That is good behaviour — it invented
nothing — but it is prose, not the refusal path, so the check fired on every
Grenzfall.

**Prose hedging now satisfies 4.4.** An answer that says it cannot answer from
the retrieved context, rather than inventing one, meets what the technique is
asking for. The cost, and it is a real one: recognising that is not a string
comparison, so Stufe 1 traded a deterministic check for a judged one. The exact
string is still the cheap path and needs no model call; everything else is
asked of the judge, once per case on the first repeat. A judge that cannot be
reached falls back to the literal comparison, which is the old behaviour and
sends a human to look.

The second direction was previously invisible and is now caught: an *ordinary*
question that gets hedged means retrieval found nothing useful for something
the corpus should cover.

## Judge

Only 4.1 and 4.2, as drafted: those compare answers *to each other*, which a
script cannot.

**`qwen3-8-27b`**, chosen by measuring rather than by size (#112). Five
comparison cases were put to the four plausible hub models; it was the only one
that caught both a changed Aktenzeichen and a dropped "grundsätzlich" while
still passing two paraphrase controls. `ministral-3-14b` missed the changed
source, which is exactly what the two reference fields exist to catch.

Two things worth keeping in mind:

- a reasoning model spends completion tokens before emitting content.
  `gpt-oss-120b` returned `finish_reason: length` with an empty message at 20
  tokens, which would have read as a judge declining to answer.
- a judge that cannot be read is a finding, never a pass. Marking a case clean
  because a request timed out is the quietest way this process could lie.

## ragas

Not built. Still true that it covers about one of six checks and cannot do 4.1,
4.2, 4.3a, 4.3b or any of the process. If it is added, the caveat stands:
faithfulness asks whether a claim is grounded in *any* retrieved context, 4.3c
asks whether it is supported by *the cited* source.

## Triage

Built as drafted (#115).

```
Grenzfall            → review, always, never filtered
any check auffällig  → review
judge auffällig      → review
clean → pool → seeded sample → review, tagged Stufe 3
```

The seed is stored on the run, so a sample can be recomputed later and shown to
be what it claims. A Grenzfall that a check also flagged is recorded as a
Grenzfall, not as Stufe 2 — it was never eligible for filtering, and recording
it otherwise would credit Stufe 1 with a catch it was not asked to make.

## Review screen

Built (#102, #104). Queue left, answer with a tab per repeat centre, the case
read-only right, one assessment sheet below.

- the answer pane reuses the explorer's source cards, without its feedback
  controls — those belong to somebody searching, not somebody assessing
- the cited PDF opens under the answer, not in a modal or a tab: 4.3c is a
  judgement about the claim and the passage together
- **the machine verdict is not in the response until the human submits.** Not
  hidden by the screen — absent from the queue entirely, with its own endpoint.
  Section 6 makes the Stufe-1-versus-human disagreement the headline number,
  and it measures anchoring instead if the reviewer sees the machine's answer
  first
- a human verdict never overwrites a machine one; both rows are kept
  > **Changed.** The draft implied a verdict per answer. Section 6 is
  > "Dokumentation je Testfall", and `Reproduzierbar? einmalig / wiederholt`
  > asks whether a finding recurred across the repeats — a question no single
  > answer can be asked. One sheet per case, with a Kernbefund per repeat
  > inside it (#100).

## Asks on SENTRA

1. `debug: true` → raw hits — **landed** (#91), with `finish_reason` and the
   served model id
2. `finish_reason` / `truncated` — **landed** (#91)
3. model id from the hub, per response — **landed** (#91). Not yet used to
   replace the harness's own `CHAT_MODEL_UNDER_TEST` setting, which means two
   processes still have to agree on a name
4. ~~`GET /api/prompts`~~ **done as `GET /api/config` (#37)**
5. delete-by-document before upsert — **landed** (#83)
6. page provenance through the chunker — **landed** (#134: #180, #182, #184,
   #186, #188). Page *and* paragraph, since WD expects finer than section
   level. Unblocks 4.3a in code; the corpus still has to be re-ingested before
   any of it is visible
7. wire up `/api/feedback` → "Testfall aus Feedback erstellen" — **landed**
   (#121)

## Open

- ~~**section vs page citations**~~ **decided and built** (decided 2026-09-18,
  extended 2026-09-19, built #134): WD expects finer than section level —
  **paragraph, with the page as well.** Provenance is carried through ingestion
  and 4.3a has its check (#189).

  **The re-ingest has not run**, and nothing above is visible until it does.
  ~24k chunks, and it is not only a cost: it also clears the 17 orphaned points
  the registry found. Until then every answer's chunks carry no page and the
  check answers `nicht prüfbar` — which is the correct answer and not a
  passing one, but it does mean 4.3a is measuring nothing yet.

  These notes previously said paragraph "is not something Docling gives for
  free". That was wrong, and checking cost one file: a Docling `TextItem` *is*
  a paragraph and carries its own `prov` with `page_no`, `bbox` and `charspan`.
  On `WD 5-077-23.pdf`, 242 of 242 text items carry a page, and the labels
  separate body text from `footnote` and `caption` — which matters, because
  counting a footnote as a paragraph would misplace citations in exactly the
  documents that have the most of them.

  What remains open is how a paragraph is **numbered**, and it is baked into
  every chunk so it wants settling before the re-ingest rather than after. Per
  page, restarting each page, is the recommendation: "page 4, third paragraph"
  is something a reviewer holding the PDF can verify by counting, and 4.3a is
  answered by a human. Document-wide numbering is stable, unambiguous, and no
  use to somebody counting down a page.
- ~~**auth**: still none~~ **partly closed** (2026-09-19). SENTRA has a
  prototype login with roles, and `Tester/in` now comes from the signed-in
  reviewer rather than being typed — #164, #177. `Varianten freigegeben durch`
  is still typed.

  It is not verification. The harness is a separate process with no session of
  its own, so it receives a name rather than checking one: the ordinary path
  records the truth without anybody typing it, and a client could still send
  anything. Proof needs signature verification against the IdP, which needs an
  IdP to be chosen — #161 item 3.
- **the Aktenzeichen on every case** has to be looked up by hand. Deliberately
  not automated: a helper that searched the corpus would let the system under
  test choose its own yardstick.
- **the Stufe-3 sample rate**, 10% by default, is the Vorlage's suggestion
  rather than a calibrated figure. The disagreement rate is what would calibrate
  it, and that needs rounds.
- **~180 generation calls per round** was the draft's estimate at 20–29s each.
  Measured on the live hub: 5.7s and 11.3s. A round is cheaper than budgeted.
- German UI and reports, English code — held throughout.

## What has not happened

One smoke round has run end to end: two cases, one repeat, against the live
corpus. It found five defects and one open question, all recorded above.

Nothing else has run for real. No full round, no reviewer has used the screen,
and the disagreement rate has never been computed over actual human verdicts —
so the number the whole process is calibrated by is implemented and untested
against reality.
