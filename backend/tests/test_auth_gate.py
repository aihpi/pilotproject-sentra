"""The gate in front of writing and in front of personal data.

Offline: nothing here needs Qdrant or the hub, because the guard runs before
any of that. The two endpoints are the ones with nothing in front of them on a
service published as a bare LoadBalancer — a re-index writes to the corpus WD
reads as authoritative, and the feedback file is user-typed questions, which
are personal data under DSGVO.

The property that is easiest to get wrong, and the one most worth a test, is
the *unset* case. The endpoints stay open when no token is configured, which is
a deliberate trade — and it is only defensible while the service says so. A
control that is switched off while `/api/health` answers "healthy" is worse
than no control, because it reads as protection.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentra.api.auth import require_token
from sentra.config import Settings, get_settings

TOKEN = "ein-geheimnis-das-niemand-erraet"


def _app() -> FastAPI:
    """Just the guard, on a route of its own.

    The real endpoints need Qdrant to build their dependencies, and what is
    under test is whether the request gets past the door — not what is behind
    it.
    """
    app = FastAPI()

    @app.post("/geschuetzt", dependencies=[__import__("fastapi").Depends(require_token)])
    def guarded() -> dict:
        return {"ok": True}

    return app


@pytest.fixture
def client_with(monkeypatch):
    def build(token: str) -> TestClient:
        app = _app()
        app.dependency_overrides[get_settings] = lambda: Settings(
            ai_hub_base_url="http://hub.invalid/v1",
            ai_hub_api_key="nicht-echt",
            admin_token=token,
        )
        return TestClient(app)

    return build


class TestWhenATokenIsConfigured:
    def test_a_caller_without_one_is_refused(self, client_with):
        response = client_with(TOKEN).post("/geschuetzt")

        assert response.status_code == 401

    def test_it_says_how_to_authenticate_rather_than_what_was_wrong(self, client_with):
        """No hint about which header or how close the value was. That is only
        useful to somebody guessing."""
        response = client_with(TOKEN).post("/geschuetzt")

        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert TOKEN not in response.text

    def test_a_bearer_token_gets_through(self, client_with):
        response = client_with(TOKEN).post(
            "/geschuetzt", headers={"Authorization": f"Bearer {TOKEN}"}
        )

        assert response.status_code == 200

    def test_the_x_header_gets_through_too(self, client_with):
        """Two headers because two kinds of caller: the harness reaches for
        Authorization, and a browser fetch can set X-Admin-Token without
        colliding with whatever an eventual login puts in Authorization."""
        response = client_with(TOKEN).post("/geschuetzt", headers={"X-Admin-Token": TOKEN})

        assert response.status_code == 200

    def test_the_wrong_token_is_refused(self, client_with):
        response = client_with(TOKEN).post("/geschuetzt", headers={"X-Admin-Token": "falsch"})

        assert response.status_code == 401

    def test_a_prefix_of_the_token_is_refused(self, client_with):
        """compare_digest, not startswith and not ==."""
        response = client_with(TOKEN).post("/geschuetzt", headers={"X-Admin-Token": TOKEN[:-1]})

        assert response.status_code == 401

    def test_bearer_is_matched_case_insensitively(self, client_with):
        """The scheme is case-insensitive per RFC 7235, and clients differ."""
        response = client_with(TOKEN).post(
            "/geschuetzt", headers={"Authorization": f"bearer {TOKEN}"}
        )

        assert response.status_code == 200


class TestWhenNoTokenIsConfigured:
    def test_the_endpoint_stays_open(self, client_with):
        """Deliberate. A pilot that answers 401 to everything the moment it is
        updated is a pilot that gets rolled back, and a developer running
        compose should not need a secret to start."""
        response = client_with("").post("/geschuetzt")

        assert response.status_code == 200

    def test_and_the_service_says_so(self):
        """The other half of that trade, and the half that makes it honest."""
        from sentra.api.auth import OPEN, PROTECTED, write_paths_state

        settings = Settings(
            ai_hub_base_url="http://hub.invalid/v1", ai_hub_api_key="x", admin_token=""
        )

        assert write_paths_state(settings) == OPEN
        assert write_paths_state(settings.model_copy(update={"admin_token": TOKEN})) == PROTECTED

    def test_it_warns_at_startup_too(self, caplog):
        """Belt and braces: the health field is for whoever looks, the log is
        for whoever tails."""
        import logging

        from sentra.api.auth import warn_if_open

        settings = Settings(
            ai_hub_base_url="http://hub.invalid/v1", ai_hub_api_key="x", admin_token=""
        )

        with caplog.at_level(logging.WARNING):
            warn_if_open(settings)

        assert "ADMIN_TOKEN" in caplog.text

    def test_and_stays_quiet_when_it_is_set(self, caplog):
        import logging

        from sentra.api.auth import warn_if_open

        settings = Settings(
            ai_hub_base_url="http://hub.invalid/v1", ai_hub_api_key="x", admin_token=TOKEN
        )

        with caplog.at_level(logging.WARNING):
            warn_if_open(settings)

        assert caplog.text == ""


class TestWhatIsNotGuarded:
    def test_the_document_paths_are_deliberately_left_open(self):
        """The corpus is published Bundestag material. Treating it as
        confidential protects the wrong things — the assets are the hub key,
        index integrity and the feedback file, which is what these notes say.

        Asserted on the route table so that adding the guard to a read path
        later is a deliberate act rather than a copied decorator."""
        from sentra.api.routes import router

        guarded = {
            getattr(route, "path", "")
            for route in router.routes
            if any(
                getattr(d, "dependency", None) is require_token
                for d in getattr(route, "dependencies", [])
            )
        }

        assert guarded == {"/api/ingest", "/api/feedback"}
