# Test cases

One YAML file per test round, applied with:

```bash
cd backend
uv run python -m sentra.evaluation.cli import eval_cases/<file>.yaml
uv run python -m sentra.evaluation.cli export eval_cases/<file>.yaml   # writes back
```

Import is idempotent: running it twice changes nothing the second time. That is
what lets the file be the thing under review — a case arrives as a diff in a
pull request rather than as a row somebody typed into a database.

**Test-IDs are allocated by the backend.** A new case is written without one and
the next export adds it. That asymmetry is deliberate: the Vorlage requires a
number never be reused, including for withdrawn cases, and a hand-written ID is
how one gets reused. `--allow-new-ids` exists only for restoring an exported
file into an empty database.

**`status: freigegeben` approves the case.** The pull request that changed the
file is the review, which is the same act the approve button performs. An
approved version can never be edited again; changing its content in the file
adds a new draft version and leaves the approved one exactly as the round that
used it measured against.

Per `docs/Vorlage_Strukturierte_Testverfahren_KISZ.md`, a round is 15 to 25
cases, at least five of them with a clear footnote or source reference, and the
`referenz_falsch` field is what makes 4.3b a real check — without a plausible
wrong source on the same topic there is nothing for the model to reach for.
