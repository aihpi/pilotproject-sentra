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

    # Where the runner finds SENTRA. Over HTTP and never in process, because
    # the API layer is part of what is under test — in-process calls would skip
    # the request models, the routing and the error policy, which is where a
    # regression is most likely to hide. Defaults to talking to ourselves.
    sentra_base_url: str = "http://localhost:8000"


@lru_cache
def get_eval_settings() -> EvalSettings:
    return EvalSettings()
