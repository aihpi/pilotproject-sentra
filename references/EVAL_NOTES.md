# Eval harness notes

Implementation notes for `Vorlage_Strukturierte_Testverfahren_KISZ.md` v0.3,
which is in this folder.

These began as a design draft written before any of the harness existed, and
were rewritten afterwards to describe what was built. Several decisions in the
draft were reversed by evidence. Those are marked as reversed rather than
edited away, because the reasoning that changed them is the part worth reading.

## Shape

The harness is its own distribution and its own process: `evaluation/`, package
`sentra_eval`, with its own pyproject, lockfile, image and uvicorn entrypoint.
It depends on nothing of SENTRA's.

> Reversed. The draft specified a modular monolith, a module with its own
> router rather than a second service, and that is what was built first (#74).
> The decision changed in #89. Something whose job is to measure SENTRA should
> not share its lifecycle, and a harness that cannot be restarted without
> restarting the thing it measures is not independent whatever its import graph
> says. The change was cheap because the HTTP boundary described below was
> insisted on from the start: the runner, case store, checks and migrations
> were untouched by the move.

The runner reaches SENTRA over HTTP at `SENTRA_BASE_URL`, never in process,
because the API layer is part of what is under test.

Eval data lives in its own Postgres container behind a compose profile.
`docker compose up` brings up SENTRA alone; `--profile eval up` adds the
harness.

The judge is a different model from the one under test, asserted at harness
startup.

The frontend gains a third view. nginx routes `/api/eval` to the harness, so
the browser still sees a single origin. The draft's same-origin requirement
survived; nginx simply gained a route.

## Properties inherited from SENTRA's design

All three held.

There is no session state anywhere, so the Vorlage's requirement in 4.1 for
three separate sessions is three POSTs in a loop.

`system_prompt` is echoed back, including on the no-results path, which gives
provenance per call with no side table.

`sources[]` is keyed by Aktenzeichen, which makes 4.3b a set comparison.

> The third carries a caveat the draft missed. The Vorlage's reference-source
> fields hold human citations, its own example being "GOBT § 35", while SENTRA
> cites its own documents. Comparing those two vocabularies compares nothing.
> A case therefore carries both: the citation a reviewer reads, and the
> Aktenzeichen the check matches on (#86). Somebody has to look the latter up
> by hand, and until they do, both source checks report "nicht prüfbar".

## Traps

| Trap | Status |
|---|---|
| `answer` uses `top_k` raw at 10, while `documents` uses `top_k*3` with `_aggregate_docs` | Live, and measured. The recall probe exists for it: a source missing from an answer is usually a chunk at rank 11 |
| `[n]` markers are an unenforced convention | Checked (#93). Dangling markers are a finding; uncited sources are evidence only, after the first real round flagged every hedging answer |
| `store.search` swallows a bad year and drops the date filter | Fixed (#70) |
| `Kurzinformation` and anything under 1000 characters becomes a single chunk | Live, unmeasured |
| `_complete` discards `finish_reason` | Fixed (#91). Truncation is its own check |
| Point ids with no delete before upsert | Fixed (#83). Existing indexes still hold their orphans, and a repair pass is a separate decision |

## Technique 4.3a

`format_context()` gives the model exactly `[Quelle: <AZ>, Abschnitt:
<section_title>]` followed by chunk text. There is no page, no paragraph and no
offset. Docling knows both, and the chunker discards them, because `parse_pdfs`
exports to Markdown and the export does not carry provenance. The model cannot
cite finer than a section.

WD expects finer than section level (2026-09-18), and specifically paragraph
with the page alongside it (2026-09-19). The question the draft left open,
section-level verification against provenance through the chunker and a full
re-ingest, is therefore settled in favour of the expensive option. That work is
tracked as #134.

The paragraph half turned out to be free rather than extra. A Docling
`TextItem` is a paragraph and carries its own page. In a normal Ausarbeitung,
242 of 242 items have one.

Marker alignment is as far as automation reaches until that lands, and it is
not a substitute. It checks that the markers in an answer line up with the
sources returned, not that the cited passage says what the answer claims, which
is what 4.3a asks. A section can run for four pages, and a reviewer told to
look in section 2.1 cannot perform 4.3a by hand either. Page 4, third
paragraph, they can, which is why the anchor has to be that fine.

The consequence for the harness is small, being a check that compares a cited
paragraph against the one a claim was drawn from. The consequence for ingestion
is not. Chunking has to move from splitting a Markdown string to walking the
document's items, and every existing point has to be re-ingested, because a
page number cannot be added to a payload that was never given one.

## Cases

As drafted, and all of it holds.

Versions are immutable, and an approved version cannot be edited at all.
Test-IDs are allocated by the backend from a counter and never reused,
including for withdrawn cases, which `max(number)+1` would not have guaranteed.
Variants are proposed once, approved by a person, and frozen into the version.
YAML import and export work in both directions and are idempotent.

## Deterministic checks

No model is involved in any of these.

| Check | Vorlage | Status |
|---|---|---|
| Source set difference | 4.3b | Built (#87) |
| Retrieval recall | new | Built (#87) |
| Marker alignment | 4.3a, partial | Built (#93) |
| Refusal | 4.4 | Built (#93), judged rather than literal since #109 |
| Truncation | new | Built (#93) |
| Byte-identical duplicate across two of three repeats | 4.1 shortcut | Built (#93), and saves a judge call when repeats match |

Technique 4.4 did not work as the draft assumed, and the decision was taken in
issue #109. The exact refusal string only appears when retrieval returns
nothing, and vector search always returns the top k however irrelevant they
are. Asked a deliberately absurd question, SENTRA retrieved ten unrelated
chunks and answered "Die Frage kann nicht ausreichend beantwortet werden, da
der Kontext keine Informationen über … enthält". That is good behaviour, since
it invented nothing, but it is prose rather than the refusal path, so the check
fired on every Grenzfall.

Prose hedging now satisfies 4.4. An answer that says it cannot answer from the
retrieved context, rather than inventing one, meets what the technique asks
for. The cost is real: recognising that is not a string comparison, so Stufe 1
traded a deterministic check for a judged one. The exact string remains the
cheap path and needs no model call. Everything else is put to the judge, once
per case on the first repeat. A judge that cannot be reached falls back to the
literal comparison, which is the old behaviour, and sends a human to look.

The second direction was previously invisible and is now caught. An ordinary
question that gets hedged means retrieval found nothing useful for something
the corpus should cover.

## Judge

Used only for 4.1 and 4.2, as drafted. Those compare answers to each other,
which a script cannot do.

The model is `qwen3-8-27b`, chosen by measurement rather than by size (#112).
Five comparison cases were put to the four plausible hub models. It was the
only one that caught both a changed Aktenzeichen and a dropped
"grundsätzlich" while still passing two paraphrase controls. `ministral-3-14b`
missed the changed source, which is exactly what the two reference fields exist
to catch.

Two properties of judges are worth keeping in mind. A reasoning model spends
completion tokens before emitting content: `gpt-oss-120b` returned
`finish_reason: length` with an empty message at 20 tokens, which would have
read as a judge declining to answer. And a judge that cannot be read is a
finding, never a pass. Marking a case clean because a request timed out is the
quietest way this process could lie.

## ragas

Not built. It remains true that ragas covers about one of six checks and cannot
perform 4.1, 4.2, 4.3a, 4.3b or any of the process. If it is added, one caveat
stands: faithfulness asks whether a claim is grounded in any retrieved context,
while 4.3c asks whether it is supported by the cited source.

## Triage

Built as drafted (#115).

```text
Grenzfall              review, always, never filtered
any check auffällig    review
judge auffällig        review
clean                  pool, seeded sample, review tagged Stufe 3
```

The seed is stored on the run, so a sample can be recomputed later and shown to
be what it claims. A Grenzfall that a check also flagged is recorded as a
Grenzfall rather than as Stufe 2, because it was never eligible for filtering,
and recording it otherwise would credit Stufe 1 with a catch it was not asked
to make.

## Review screen

Built in #102 and #104. The queue is on the left, the answer with one tab per
repeat is in the centre, the case is read-only on the right, and a single
assessment sheet sits below.

The answer pane reuses the explorer's source cards without its feedback
controls, which belong to somebody searching rather than somebody assessing.

The cited PDF opens under the answer rather than in a modal or a separate tab,
because 4.3c is a judgement about the claim and the passage together.

The machine verdict is not in the response until the human submits. It is not
merely hidden by the screen; it is absent from the queue entirely and has its
own endpoint. Section 6 makes the disagreement between Stufe 1 and the human
the headline number, and that number measures anchoring instead if the reviewer
sees the machine's answer first.

A human verdict never overwrites a machine one. Both rows are kept.

> Changed. The draft implied one verdict per answer. Section 6 is
> "Dokumentation je Testfall", and `Reproduzierbar? einmalig / wiederholt` asks
> whether a finding recurred across the repeats, which is a question no single
> answer can be asked. The result is one sheet per case, with a Kernbefund per
> repeat inside it (#100).

## Requests made of SENTRA

| # | Request | Status |
|---|---|---|
| 1 | `debug: true` returning raw hits | Landed (#91), with `finish_reason` and the served model id |
| 2 | `finish_reason` and `truncated` | Landed (#91) |
| 3 | Model id from the hub, per response | Landed (#91), though not yet used to replace the harness's own `CHAT_MODEL_UNDER_TEST` setting, so two processes still have to agree on a name |
| 4 | `GET /api/prompts` | Done as `GET /api/config` (#37) |
| 5 | Delete by document before upsert | Landed (#83) |
| 6 | Page provenance through the chunker | Not done, and blocks 4.3a. Scoped as #134 |
| 7 | Wire up `/api/feedback` for "Testfall aus Feedback erstellen" | Landed (#121) |

## Open questions

### Paragraph numbering

The choice between section and page citations was settled on 2026-09-18 and
extended on 2026-09-19: WD expects paragraph, with the page alongside.
Provenance has to be carried through ingestion and the corpus re-ingested,
which is #134, and 4.3a stays unimplemented until it lands.

These notes previously stated that paragraph numbering was not something
Docling gives for free. That was wrong, and checking cost one file. A Docling
`TextItem` is a paragraph and carries its own `prov` with `page_no`, `bbox` and
`charspan`. On `WD 5-077-23.pdf`, 242 of 242 text items carry a page, and the
labels separate body text from `footnote` and `caption`. That separation
matters, because counting a footnote as a paragraph would misplace citations in
exactly the documents that have the most of them.

What remains open is how a paragraph is numbered. It is baked into every chunk,
so it wants settling before the re-ingest rather than after. Per page,
restarting on each page, is the recommendation: "page 4, third paragraph" is
something a reviewer holding the PDF can verify by counting, and 4.3a is
answered by a human. Document-wide numbering is stable and unambiguous and of
no use to somebody counting down a page.

### Authorship of verdicts

Partly closed on 2026-09-19. SENTRA has a prototype login with roles, and
`Tester/in` now comes from the signed-in reviewer rather than being typed
(#164, #177). `Varianten freigegeben durch` is still typed.

This is not verification. The harness is a separate process with no session of
its own, so it receives a name rather than checking one. The ordinary path
records the truth without anybody typing it, and a client could still send
anything. Proof needs signature verification against the identity provider,
which needs an identity provider to be chosen; that is item 3 of #161.

### Remaining

The Aktenzeichen on every case has to be looked up by hand. This is
deliberately not automated: a helper that searched the corpus would let the
system under test choose its own yardstick.

The Stufe 3 sample rate, 10 percent by default, is the Vorlage's suggestion
rather than a calibrated figure. The disagreement rate is what would calibrate
it, and that needs rounds.

The draft estimated roughly 180 generation calls per round at 20 to 29 seconds
each. Measured against the live hub, the figures are 5.7 and 11.3 seconds, so a
round is cheaper than budgeted.

German for the UI and reports, English for the code. Held throughout.

## State of validation

One smoke round has run end to end: two cases, one repeat, against the live
corpus. It found five defects and one open question, all recorded above.

Nothing else has run for real. There has been no full round, no reviewer has
used the screen, and the disagreement rate has never been computed over actual
human verdicts. The number the whole process is calibrated by is implemented
and untested against reality.
