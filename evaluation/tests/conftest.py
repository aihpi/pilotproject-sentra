"""Shared fixtures for the harness test suite.

Two tiers, the same split SENTRA's suite uses:
  - no marker: runs offline, no Postgres and no SENTRA
  - @pytest.mark.integration: needs the eval database

SENTRA itself is never needed. The runner is an HTTP client, so it is stubbed
through httpx.MockTransport — which is also what keeps the suite from spending
AI Hub quota on every push.
"""

import os
from pathlib import Path

EVALUATION_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = EVALUATION_DIR / ".env"

# A judge that could not be reached if anything tried. Offline tests read the
# settings and never call it, so a placeholder that cannot resolve is safer
# than one that might find something real.
PLACEHOLDER_JUDGE_HUB = "http://judge.invalid/v1"
PLACEHOLDER_JUDGE_KEY = "offline-tests-do-not-call-the-judge"
PLACEHOLDER_JUDGE_MODEL = "offline-placeholder-judge"


def _placeholders_if_absent(env_file: Path) -> None:
    """Let the settings build with no .env and no environment.

    The same problem SENTRA's suite had, and the same fix: the offline tier
    calls no judge, so it should not need judge credentials to construct a
    Settings object for its collection names and paths. CI has neither a .env
    nor secrets.

    Nothing is set when an env file exists: environment variables outrank the
    dotenv file in pydantic-settings, so doing it unconditionally would replace
    a real judge with an unreachable one.
    """
    if env_file.is_file():
        return
    os.environ.setdefault("JUDGE_BASE_URL", PLACEHOLDER_JUDGE_HUB)
    os.environ.setdefault("JUDGE_API_KEY", PLACEHOLDER_JUDGE_KEY)
    os.environ.setdefault("JUDGE_MODEL", PLACEHOLDER_JUDGE_MODEL)
    os.environ.setdefault("CHAT_MODEL_UNDER_TEST", "llama-3-3-70b")


_placeholders_if_absent(ENV_FILE)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: requires the eval database (skip with -m 'not integration')"
    )
