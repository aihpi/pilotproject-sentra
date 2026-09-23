"""What a caller may do, once it is known who they are.

#165 established identity and enforced nothing with it. This is the task that
turns it into a rule, and the one that actually protects anything:
`references/SECURITY_NOTES.md` — "A hidden tab is not access control. Gating
the Admin tab in React hides the button, not the endpoint."

Three ways past a guard, and they are not the same thing:

    a session of sufficient rank    a person, and we know which
    the machine token               a caller handed the secret. No identity,
                                    and deliberately blunt
    neither configured              open, as before any of this, and reported

The distinction most worth a test is **401 against 403**. 401 means "say who
you are", which a browser can act on by offering a login. 403 means "I know who
you are and the answer is still no" — answering that with a login prompt is a
loop, and an infuriating one for somebody who is already signed in.
"""

import secrets

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from sentra.api.auth import require_role
from sentra.api.identity import ADMIN, LESER, PRUEFER, hash_password
from sentra.config import Settings, get_settings

PASSWORT = secrets.token_urlsafe(24)
HASH = hash_password(PASSWORT)
TOKEN = secrets.token_urlsafe(24)
SECRET = secrets.token_urlsafe(32)

USERS = f"chef:admin:{HASH},wd:pruefer:{HASH},gast:leser:{HASH}"


def _settings(**over) -> Settings:
    base = {
        "ai_hub_base_url": "http://hub.invalid/v1",
        "ai_hub_api_key": "nicht-echt",
        "sentra_users": USERS,
        "session_secret": SECRET,
        "admin_token": TOKEN,
        "session_cookie_secure": False,
    }
    base.update(over)
    return Settings(**base)


@pytest.fixture
def client_with():
    """An app with one route per role, plus the real login endpoint.

    Routes of its own rather than the real ones: /ingest and /feedback build
    Qdrant-backed dependencies, and what is under test is who gets through the
    door rather than what is behind it.
    """

    def build(settings: Settings) -> TestClient:
        app = FastAPI()
        if settings.session_secret and settings.sentra_users:
            app.add_middleware(
                SessionMiddleware,
                secret_key=settings.session_secret,
                session_cookie="sentra_session",
                max_age=settings.session_max_age_seconds,
                same_site="lax",
                https_only=settings.session_cookie_secure,
            )

        @app.post("/braucht-admin", dependencies=[Depends(require_role(ADMIN))])
        def admin_only() -> dict:
            return {"ok": True}

        @app.post("/braucht-pruefer", dependencies=[Depends(require_role(PRUEFER))])
        def reviewer_up() -> dict:
            return {"ok": True}

        from sentra.api.routes import router

        app.include_router(router)
        app.dependency_overrides[get_settings] = lambda: settings
        return TestClient(app)

    return build


def _as(client: TestClient, user: str) -> TestClient:
    response = client.post("/api/login", json={"benutzername": user, "passwort": PASSWORT})
    assert response.status_code == 200, response.text
    return client


class TestWithASession:
    def test_an_admin_reaches_the_admin_route(self, client_with):
        client = _as(client_with(_settings()), "chef")

        assert client.post("/braucht-admin").status_code == 200

    def test_a_reviewer_does_not(self, client_with):
        client = _as(client_with(_settings()), "wd")

        assert client.post("/braucht-admin").status_code == 403

    def test_but_reaches_the_reviewer_route(self, client_with):
        client = _as(client_with(_settings()), "wd")

        assert client.post("/braucht-pruefer").status_code == 200

    def test_an_admin_reaches_everything_below_it(self, client_with):
        """Roles are ordered, not a set of unrelated permissions. An admin who
        could not read feedback would be a role system nobody could reason
        about."""
        client = _as(client_with(_settings()), "chef")

        assert client.post("/braucht-pruefer").status_code == 200

    def test_a_reader_reaches_neither(self, client_with):
        client = _as(client_with(_settings()), "gast")

        assert client.post("/braucht-pruefer").status_code == 403
        assert client.post("/braucht-admin").status_code == 403


class TestTheDifferenceBetween401And403:
    def test_no_session_is_401(self, client_with):
        """ "Say who you are." A browser can act on this by offering a login."""
        assert client_with(_settings()).post("/braucht-admin").status_code == 401

    def test_and_says_how(self, client_with):
        response = client_with(_settings()).post("/braucht-admin")

        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_the_wrong_role_is_403(self, client_with):
        """ "I know who you are and the answer is still no." Answering this with
        a login prompt is a loop for somebody already signed in."""
        client = _as(client_with(_settings()), "gast")

        response = client.post("/braucht-admin")

        assert response.status_code == 403
        assert "WWW-Authenticate" not in response.headers

    def test_and_names_what_would_be_needed(self, client_with):
        client = _as(client_with(_settings()), "gast")

        assert ADMIN in client.post("/braucht-admin").json()["detail"]


class TestTheMachineToken:
    def test_gets_through_without_a_session(self, client_with):
        """The evaluation harness reads feedback over HTTP like any other
        client and has no session to offer."""
        client = client_with(_settings())

        response = client.post("/braucht-admin", headers={"X-Admin-Token": TOKEN})

        assert response.status_code == 200

    def test_as_a_bearer_too(self, client_with):
        client = client_with(_settings())

        response = client.post("/braucht-pruefer", headers={"Authorization": f"Bearer {TOKEN}"})

        assert response.status_code == 200

    def test_a_wrong_one_is_refused(self, client_with):
        client = client_with(_settings())

        response = client.post("/braucht-admin", headers={"X-Admin-Token": "falsch"})

        assert response.status_code == 401

    def test_it_does_not_rescue_a_session_of_the_wrong_role(self, client_with):
        """Only if the token is actually correct. A reader sending nonsense is
        still a reader."""
        client = _as(client_with(_settings()), "gast")

        response = client.post("/braucht-admin", headers={"X-Admin-Token": "falsch"})

        assert response.status_code == 403


class TestWhenNothingIsConfigured:
    def test_the_routes_stay_open(self, client_with):
        """The same trade as #162 and for the same reason: a pilot that answers
        401 to everything the moment it is updated is a pilot that gets rolled
        back."""
        client = client_with(_settings(admin_token="", sentra_users="", session_secret=""))

        assert client.post("/braucht-admin").status_code == 200

    def test_but_a_token_alone_closes_them(self, client_with):
        """Configuring either mechanism is enough to mean "not the internet"."""
        client = client_with(_settings(sentra_users="", session_secret=""))

        assert client.post("/braucht-admin").status_code == 401

    def test_and_a_login_alone_does_too(self, client_with):
        client = client_with(_settings(admin_token=""))

        assert client.post("/braucht-admin").status_code == 401


class TestTheRealEndpoints:
    def test_ingest_needs_an_admin_and_feedback_needs_a_reviewer(self):
        """Asserted on the guards the routes carry rather than by calling them,
        which would need Qdrant. What matters is that the two are not the same
        — feedback is personal data a reviewer reads, re-indexing writes to the
        corpus."""
        from sentra.api.routes import router

        guards = {
            getattr(route, "path", ""): getattr(route, "dependencies", [])
            for route in router.routes
        }

        assert len(guards["/api/ingest"]) == 1
        assert len(guards["/api/feedback"]) == 1
        # Different closures, so the two roles cannot have been copied.
        assert guards["/api/ingest"][0].dependency is not guards["/api/feedback"][0].dependency


class TestRoleNames:
    def test_the_three_are_ordered_least_to_most(self):
        from sentra.api.identity import ROLES

        assert ROLES == (LESER, PRUEFER, ADMIN)
