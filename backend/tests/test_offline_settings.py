"""The offline tier builds Settings without AI Hub credentials. Only the tier.

Settings requires ai_hub_base_url and ai_hub_api_key and gives them no default,
which is what makes the application refuse to start rather than boot against a
hub that is not there. The test suite inherited that requirement without
needing it: none of the offline tests calls the hub, they want a Settings for
its collection names and paths. CI has no .env and no secrets, so the whole
offline tier errored out of the settings fixture before any test body ran.

conftest supplies placeholders when nothing else does. These tests pin the two
halves of that: it fills the gap where there is one, and it stays out of the
way everywhere else — including in config.py, where the requirement is the
point and must not quietly acquire a default.
"""

import os
from urllib.parse import urlparse

import pytest
from pydantic import ValidationError

from sentra.config import Settings
from tests.conftest import (
    PLACEHOLDER_HUB,
    PLACEHOLDER_KEY,
    _placeholder_credentials_if_absent,
)

CREDENTIALS = ("AI_HUB_BASE_URL", "AI_HUB_API_KEY")


@pytest.fixture
def without_credentials(monkeypatch):
    """No credentials in the environment, whichever machine this runs on."""
    for name in CREDENTIALS:
        monkeypatch.delenv(name, raising=False)


class TestConfigStillRequiresThem:
    """The decision the placeholders must not erode.

    .env.example says "No defaults, the application will not start without
    these". A default added to config.py to make CI green would trade a loud
    failure at boot for a 503 on somebody's first search.
    """

    def test_settings_refuses_to_build_without_them(self, without_credentials):
        with pytest.raises(ValidationError) as caught:
            Settings(_env_file="/nonexistent/.env")

        missing = {error["loc"][0] for error in caught.value.errors()}
        assert missing == {"ai_hub_base_url", "ai_hub_api_key"}


class TestThePlaceholders:
    def test_they_fill_the_gap(self, without_credentials, tmp_path):
        _placeholder_credentials_if_absent(tmp_path / "absent.env")

        assert os.environ["AI_HUB_BASE_URL"] == PLACEHOLDER_HUB
        assert os.environ["AI_HUB_API_KEY"] == PLACEHOLDER_KEY

    def test_settings_builds_with_them(self, without_credentials, tmp_path):
        _placeholder_credentials_if_absent(tmp_path / "absent.env")

        assert Settings(_env_file="/nonexistent/.env").ai_hub_base_url == PLACEHOLDER_HUB

    def test_the_hub_cannot_resolve(self):
        """So a test that does call the hub fails on DNS rather than finding
        something real. A placeholder that worked would hide the next mistake."""
        host = urlparse(PLACEHOLDER_HUB).hostname

        assert host is not None and host.endswith(".invalid")


class TestTheyStayOutOfTheWay:
    def test_a_real_environment_value_is_kept(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AI_HUB_BASE_URL", "https://real-hub.example.com/v1")

        _placeholder_credentials_if_absent(tmp_path / "absent.env")

        assert os.environ["AI_HUB_BASE_URL"] == "https://real-hub.example.com/v1"

    def test_an_env_file_is_left_to_pydantic(self, without_credentials, tmp_path):
        """The one that would break a developer machine if it regressed.

        Environment variables outrank the dotenv file, so setting a placeholder
        while a real .env exists would replace working credentials with a hub
        that cannot be reached, and take the integration tier with it.
        """
        env_file = tmp_path / ".env"
        env_file.write_text("AI_HUB_BASE_URL=https://from-the-file.example.com/v1\n")

        _placeholder_credentials_if_absent(env_file)

        assert "AI_HUB_BASE_URL" not in os.environ
