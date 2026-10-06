"""Configuration for the evaluation harness.

Separate from sentra.config.Settings on purpose. SENTRA has to boot without any
of this: the harness is optional, its dependencies are an extra, and an image
built without them must still serve /api/explorer exactly as before. So the
core settings know one thing about evaluation — whether it is switched on — and
everything the harness itself needs lives here, read the first time it is asked
for, which is after main has already decided to mount it.
"""

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class EvalSettings(BaseSettings):
    """What the harness needs, from the same .env as everything else.

    The judge credentials have no defaults, matching the AI Hub ones in
    sentra.config. A harness pointed at a judge that is not there should refuse
    to start rather than fail on the first comparison it is asked to make.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Settings owns the rest of that file. pydantic-settings forbids extra
        # keys by default, so without this every key belonging to Settings
        # reads here as an extra and EvalSettings refuses to build at all.
        extra="ignore",
    )

    # The judge. A different model from CHAT_MODEL, and normally a different
    # hub: the Vorlage asks for a check that shares neither model nor prompt
    # structure with SENTRA, because one that does relocates a consistency
    # problem rather than detecting it.
    # Optional here, required in practice, and the difference matters. These
    # are needed to run a round; they are not needed to reach the database.
    # Declared required, `alembic upgrade head` could not run without judge
    # credentials, which is a deployment step that has nothing to do with a
    # judge — the same shape of mistake as the offline test suite demanding AI
    # Hub credentials it never used (#71).
    #
    # judge_config() in judge.py is where they become required, with a message
    # naming what is missing, and mount_evaluation calls it at boot. So a
    # harness that is switched on still refuses to start without a judge.
    judge_base_url: str | None = None
    judge_api_key: str | None = None
    judge_model: str | None = None

    # The eval database. Credentials rather than a secret in the API-key sense,
    # and the default matches the compose service, so a developer who turns the
    # harness on locally needs to set nothing. A deployment overrides it.
    #
    # postgresql+psycopg is psycopg 3. The bare postgresql:// prefix would pick
    # psycopg2, which is not in the extra and would fail at connect rather than
    # at configuration.
    # 5433 is the host port compose publishes, not the container's 5432: this
    # default is for running the backend on your own machine against the compose
    # stack. Inside a container compose overrides it with eval-db:5432.
    eval_database_url: str = "postgresql+psycopg://sentra:sentra@localhost:5433/sentra_eval"

    # The embedding model ragas uses, when the optional extra is installed.
    # ragas defaults to OpenAI's text-embedding-ada-002, which this hub does
    # not serve — and the failure surfaces as a NaN score rather than an error.
    ragas_embedding_model: str = "minilm-embedding"

    # How long the runner waits on one SENTRA call. Above SENTRA's own
    # generation timeout of 120s on purpose: a call that SENTRA gives up on
    # should come back as its 503, which is a finding, rather than as the
    # runner timing out first, which is noise about the harness.
    runner_timeout_seconds: float = 180.0

    # The model SENTRA is configured to answer with, so the harness can refuse
    # to start when the judge resolves to the same one. Read from the same
    # CHAT_MODEL the backend reads: the harness is not importing SENTRA's
    # settings, it is reading the same deployment's configuration.
    chat_model_under_test: str = ""

    # Origins allowed to call the harness from a browser. Only the vite dev
    # server needs it; under compose nginx routes /api/eval here and the
    # browser sees one origin.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # Where the runner finds SENTRA. Over HTTP and never in process, because
    # the API layer is part of what is under test — in-process calls would skip
    # the request models, the routing and the error policy, which is where a
    # regression is most likely to hide. Defaults to talking to ourselves.
    # SENTRA's write path and its feedback endpoint are guarded by a token
    # (#162), and reading feedback to draft cases from it is exactly the kind
    # of caller that needs one. Empty where SENTRA has none configured, which
    # is the compose default.
    #
    # It is not the judge's key and not the hub's: this one says "a caller that
    # was given SENTRA's secret", which is all SENTRA checks.
    sentra_admin_token: str | None = None

    sentra_base_url: str = "http://localhost:8000"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept CORS_ORIGINS as a comma-separated string or a JSON array."""
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                import json

                return json.loads(raw)
            return [part.strip() for part in raw.split(",") if part.strip()]
        return value


@lru_cache
def get_eval_settings() -> EvalSettings:
    return EvalSettings()


def sentra_headers(settings: EvalSettings) -> dict[str, str]:
    """What every request to SENTRA carries, which is a token or nothing.

    **Sent only when configured**, and that is not laziness. SENTRA leaves its
    guarded endpoints open when it has no token of its own, and a harness that
    refused to work in that case would be enforcing a rule SENTRA is not
    applying — including against a developer's compose stack, which has none.

    Shared because it was not: the token was read in `feedback` and nowhere
    else, so the runner reached SENTRA anonymously while the config field read
    as though the harness were an authenticated client. One of two call sites
    is the shape a setting takes when it is about to be quietly wrong.
    """
    if not settings.sentra_admin_token:
        return {}
    return {"Authorization": f"Bearer {settings.sentra_admin_token}"}
