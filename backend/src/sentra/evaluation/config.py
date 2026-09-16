"""Configuration for the evaluation harness.

Separate from sentra.config.Settings on purpose. SENTRA has to boot without any
of this: the harness is optional, its dependencies are an extra, and an image
built without them must still serve /api/explorer exactly as before. So the
core settings know one thing about evaluation — whether it is switched on — and
everything the harness itself needs lives here, read the first time it is asked
for, which is after main has already decided to mount it.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    judge_base_url: str
    judge_api_key: str
    judge_model: str

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

    # Where the runner finds SENTRA. Over HTTP and never in process, because
    # the API layer is part of what is under test — in-process calls would skip
    # the request models, the routing and the error policy, which is where a
    # regression is most likely to hide. Defaults to talking to ourselves.
    sentra_base_url: str = "http://localhost:8000"


@lru_cache
def get_eval_settings() -> EvalSettings:
    return EvalSettings()
