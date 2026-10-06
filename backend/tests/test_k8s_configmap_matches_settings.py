"""Every setting is accounted for in the cluster's configmap, or listed here.

The configmap is the deployment's copy of `Settings`, kept by hand, and the
failure mode is not a wrong value — it is an absent one. An absent key falls
back to the default in `config.py`, which is written for a developer running
compose, and a default that is right on a laptop is usually wrong on a cluster.

That is not hypothetical. `REGISTRY_DATABASE_URL` was missing for the whole life
of the registry, so the deployed backend pointed at `localhost:5434` inside its
own pod and every ingested document failed to register (#196). The login
settings were missing the same way and nobody could log in (#198). Both were
invisible because nothing in the configmap was *wrong*.

So the rule is coverage, not correctness: a setting is either in the configmap,
or in `NOT_IN_CONFIGMAP` below with a reason someone wrote down. Adding a field
to `Settings` and deploying without thinking about it is the thing this stops.

The configmap is parsed by hand rather than with a YAML library, to keep the
backend's test dependencies to what the backend already installs. It only needs
the keys, and the shape it reads is asserted before it trusts it.
"""

import re
from pathlib import Path

import pytest

from sentra.config import Settings

BACKEND = Path(__file__).resolve().parents[1]
CONFIGMAP = BACKEND.parent / "k8s" / "backend" / "configmap.yaml"

# Settings the cluster deliberately does not carry in its configmap. The value
# is the reason, and it is printed on failure so that removing an entry has to
# argue with the reason rather than just delete it.
NOT_IN_CONFIGMAP = {
    "AI_HUB_API_KEY": "a secret, from sentra-secret",
    "REGISTRY_DATABASE_URL": "embeds the database password, so it lives in sentra-secret",
    "SESSION_SECRET": "a secret, and empty means no login rather than a weak one",
    "SENTRA_USERS": "carries password hashes, so it lives in sentra-secret",
    "ADMIN_TOKEN": "a secret, from sentra-secret",
    "CORS_ORIGINS": (
        "nothing reads it: nginx proxies /api from the origin the page came "
        "from, so the browser makes no cross-origin request"
    ),
    "SESSION_MAX_AGE_SECONDS": "the default is the deployment's answer",
    "SESSION_COOKIE_SECURE": (
        "defaults to on, and turning it off has to be a deliberate act with "
        "TLS in front of the cluster as the alternative -- see #198"
    ),
}


def configmap_keys() -> set[str]:
    """The keys under `data:`, read without a YAML parser.

    Only lines indented exactly two spaces inside the `data:` block count, so a
    commented-out key cannot pass for a present one.
    """
    lines = CONFIGMAP.read_text().splitlines()

    assert "data:" in lines, f"{CONFIGMAP} has no top-level `data:` block"
    body = lines[lines.index("data:") + 1 :]

    keys = set()
    for line in body:
        if line and not line.startswith(" "):
            break  # out of the data block
        if match := re.fullmatch(r"  ([A-Z][A-Z0-9_]*): .*", line):
            keys.add(match.group(1))
    return keys


class TestConfigmapCoverage:
    def test_the_configmap_is_parseable(self):
        """Guard the guard: a parser that silently reads nothing passes everything."""
        keys = configmap_keys()

        assert len(keys) > 5, f"read only {keys} from {CONFIGMAP} -- has its shape changed?"
        assert "QDRANT_URL" in keys

    @pytest.mark.parametrize("field", sorted(Settings.model_fields))
    def test_setting_is_in_the_configmap_or_deliberately_not(self, field: str):
        env_var = field.upper()

        if reason := NOT_IN_CONFIGMAP.get(env_var):
            assert env_var not in configmap_keys(), (
                f"{env_var} is in {CONFIGMAP.name} but NOT_IN_CONFIGMAP says it "
                f"should not be ({reason}). Remove one of the two."
            )
            return

        assert env_var in configmap_keys(), (
            f"{env_var} is a setting the backend reads, and the cluster's "
            f"configmap does not set it -- so the deployment gets the default "
            f"from config.py, which is written for local development.\n\n"
            f"Either add it to {CONFIGMAP}, or add it to NOT_IN_CONFIGMAP in "
            f"{Path(__file__).name} with the reason."
        )

    def test_no_stale_exemptions(self):
        """An exemption for a setting that no longer exists is a stale comment."""
        fields = {field.upper() for field in Settings.model_fields}
        stale = set(NOT_IN_CONFIGMAP) - fields

        assert not stale, f"NOT_IN_CONFIGMAP names settings that are gone: {sorted(stale)}"
