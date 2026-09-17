# Evaluation harness

Structured test rounds for SENTRA, implementing
`docs/Vorlage_Strukturierte_Testverfahren_KISZ.md`.

Its own process and its own distribution. It depends on nothing of SENTRA's and
reaches it over HTTP at `SENTRA_BASE_URL`, because SENTRA's API layer is part of
what is being tested — calling into it would skip the request models, the
routing and the error policy, which is where a regression is most likely to
hide.

```bash
cd evaluation
uv sync
uv run alembic upgrade head                     # apply the schema
uv run uvicorn sentra_eval.app:app --port 8100
```

Or as part of the stack, where it is a profile because most people bringing the
stack up are working on SENTRA rather than measuring it:

```bash
docker compose --profile eval up
```

## Configuration

Read from `backend/.env` when run through compose, or `evaluation/.env` locally.
The harness needs:

| | |
|---|---|
| `JUDGE_BASE_URL`, `JUDGE_API_KEY`, `JUDGE_MODEL` | the checking model. Required — the harness refuses to start without one |
| `CHAT_MODEL_UNDER_TEST` | so it can refuse to start when the judge resolves to the model it is meant to be checking |
| `SENTRA_BASE_URL` | where SENTRA is |
| `EVAL_DATABASE_URL` | Postgres |

`JUDGE_MODEL=qwen3-8-27b` is the measured choice — see #112 for the comparison
against the other hub models. Note that a reasoning model such as
`gpt-oss-120b` spends completion tokens before emitting content, and will
return an empty message if the token budget is tight.

The judge must not be `CHAT_MODEL`. The Vorlage is explicit that the checking
model should share neither model nor prompt structure with the system under
test, because one that does relocates a consistency problem rather than
detecting it. A round is about 180 generation calls; finding out afterwards that
every verdict was SENTRA grading itself means discarding all of them.

## Test cases

`cases/` holds them as YAML — see `cases/README.md`. Import is idempotent, so
the file is the thing under review.

## Tests

```bash
uv run pytest -m "not integration"   # no services needed
uv run pytest -m integration         # needs Postgres
```
