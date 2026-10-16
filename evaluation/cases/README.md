# Test cases

One YAML file per test round, applied with:

```bash
cd backend
uv run python -m sentra_eval.cli import eval_cases/<file>.yaml
uv run python -m sentra_eval.cli export eval_cases/<file>.yaml   # writes back
```

Import is idempotent: running it twice changes nothing the second time. That is
what lets the file be the thing under review — a case arrives as a diff in a
pull request rather than as a row somebody typed into a database.

**Numbers are allocated by the backend.** A new case is written without a
`nummer` and the next export adds it. That asymmetry is deliberate: the Vorlage
requires a number never be reused, including for withdrawn cases, and a
hand-written number is how one gets reused. `--allow-new-ids` exists only for
restoring an exported file into an empty database.

**Labels**: `kategorie`, `testart`, `frageform`, `herkunft`. A label missing
from the file leaves the case's label as it is, so re-importing an older file
does not wipe labels set on screen. See `src/sentra_eval/labels.py`.

**`tag` is a readable label, not the identity.** The export writes each case's
tag. Changing it in the file applies it on the next import and keeps it from
being regenerated; it only has to stay unique.

**`status: freigegeben` approves the case.** The pull request that changed the
file is the review, which is the same act the approve button performs. An
approved version can never be edited again; changing its content in the file
adds a new draft version and leaves the approved one exactly as the round that
used it measured against.

**Approval needs a measurable case.** Besides the expected answer, an ordinary
case (not a Grenzfall) needs the correct source and its Aktenzeichen, and that
document has to be indexed in SENTRA, which the harness asks over HTTP. A file
that approves a case whose source is not indexed yet is refused; ingest the
document first. The Testfälle table lists what each draft is still missing.

Per `references/Vorlage_Strukturierte_Testverfahren_KISZ.md`, a round is 15 to 25
cases, at least five of them with a clear footnote or source reference, and the
`referenz_falsch` field is what makes 4.3b a real check — without a plausible
wrong source on the same topic there is nothing for the model to reach for.
