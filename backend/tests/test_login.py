"""The prototype login: sessions, and the three endpoints that manage them.

Offline. Nothing here needs Qdrant or the hub — identity is established before
any of that, which is also why it can be tested without them.

Two properties are worth more than the rest.

**An unknown user and a wrong password must be indistinguishable**, in message
and in work done. Answering faster for an account that does not exist is a
user-enumeration oracle however carefully the message is worded, and this is a
pilot whose user list is a handful of named colleagues.

**No signing secret must mean no login, not a weak one.** A default key is a
forged session for anyone who can read the repository, so the absent case has
to fail closed rather than fall back.
"""

import secrets
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from sentra.api.identity import (
    ADMIN,
    LESER,
    PRUEFER,
    Subject,
    hash_password,
    parse_users,
    verify_password,
)
from sentra.api.routes import get_store, router
from sentra.config import Settings, get_settings

# Generated, not written down. A literal credential in a test file is a string
# a scanner cannot tell from a real one — and it is right to flag it, because
# what is in the repository is in the repository whatever the comment above it
# says. Generating them also means nothing here can be copied into a
# deployment and left there.
PASSWORT = secrets.token_urlsafe(24)
HASH = hash_password(PASSWORT)
SECRET = secrets.token_urlsafe(32)

# Named rather than written inline. A deliberately wrong value passed straight
# to the login call reads to a secret scanner exactly like a real one leaked —
# it cannot tell them apart, and it should not have to.
#
# Writing the offending pattern into a comment does not help either: the first
# version of this note spelled out the literal it was explaining, and was duly
# flagged for containing it. The scanner is reading the file, not the argument.
FALSCHES_PASSWORT = secrets.token_urlsafe(12)
UNLESBARER_EINTRAG = "kein-gueltiges-format"


def _settings(**over) -> Settings:
    base = {
        "ai_hub_base_url": "http://hub.invalid/v1",
        "ai_hub_api_key": "nicht-echt",
        "sentra_users": f"mario:admin:{HASH},wd:pruefer:{HASH}",
        "session_secret": SECRET,
    }
    base.update(over)
    return Settings(**base)


@pytest.fixture
def client_with():
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
        app.include_router(router)
        app.dependency_overrides[get_settings] = lambda: settings
        # /health builds a store; nothing else in this module touches it.
        app.dependency_overrides[get_store] = lambda: None
        return TestClient(app)

    return build


def _login(client: TestClient, user="mario", password=PASSWORT):
    return client.post("/api/login", json={"benutzername": user, "passwort": password})


class TestLoggingIn:
    def test_a_configured_user_gets_a_session(self, client_with):
        client = client_with(_settings(session_cookie_secure=False))

        response = _login(client)

        assert response.status_code == 200
        assert response.json() == {"benutzername": "mario", "rolle": ADMIN}

    def test_the_session_is_then_readable(self, client_with):
        client = client_with(_settings(session_cookie_secure=False))
        _login(client)

        assert client.get("/api/me").json()["rolle"] == ADMIN

    def test_the_role_comes_from_the_configuration_not_the_request(self, client_with):
        """A client that could name its own role could name admin."""
        client = client_with(_settings(session_cookie_secure=False))

        _login(client, user="wd")

        assert client.get("/api/me").json()["rolle"] == PRUEFER

    def test_logging_out_ends_it(self, client_with):
        client = client_with(_settings(session_cookie_secure=False))
        _login(client)

        assert client.post("/api/logout").status_code == 204
        assert client.get("/api/me").status_code == 401

    def test_logging_out_twice_is_not_an_error(self, client_with):
        """What somebody clicking the button twice does. It has already
        succeeded."""
        client = client_with(_settings(session_cookie_secure=False))

        assert client.post("/api/logout").status_code == 204
        assert client.post("/api/logout").status_code == 204


class TestBeingRefused:
    def test_a_wrong_password(self, client_with):
        client = client_with(_settings(session_cookie_secure=False))

        assert _login(client, password=FALSCHES_PASSWORT).status_code == 401

    def test_an_unknown_user(self, client_with):
        client = client_with(_settings(session_cookie_secure=False))

        assert _login(client, user="niemand").status_code == 401

    def test_the_two_are_indistinguishable(self, client_with):
        """Same status and same words. A different message for an unknown user
        turns the endpoint into a directory of who works here."""
        client = client_with(_settings(session_cookie_secure=False))

        unknown = _login(client, user="niemand")
        wrong = _login(client, password=FALSCHES_PASSWORT)

        assert unknown.status_code == wrong.status_code
        assert unknown.json() == wrong.json()

    def test_and_cost_about_the_same(self, client_with):
        """The reason `authenticate` verifies against a dummy hash when the
        user is missing: otherwise the unknown case skips scrypt entirely and
        answers in a fraction of the time, which is the same oracle measured
        with a stopwatch instead of read off the screen.

        A loose bound — this is a timing assertion on a test runner, so it
        catches "one does no work at all" rather than a subtle difference.
        """
        client = client_with(_settings(session_cookie_secure=False))

        start = time.perf_counter()
        _login(client, user="niemand")
        unknown = time.perf_counter() - start

        start = time.perf_counter()
        _login(client, password=FALSCHES_PASSWORT)
        wrong = time.perf_counter() - start

        assert unknown > wrong / 5, f"unknown user was far cheaper: {unknown} vs {wrong}"

    def test_no_session_means_no_me(self, client_with):
        client = client_with(_settings(session_cookie_secure=False))

        assert client.get("/api/me").status_code == 401


class TestWhenNoLoginIsConfigured:
    def test_without_a_secret_logging_in_is_refused(self, client_with):
        """Fails closed. A default signing key would be a forged session for
        anyone who can read this repository."""
        client = client_with(_settings(session_secret=""))

        assert _login(client).status_code == 503

    def test_without_users_too(self, client_with):
        client = client_with(_settings(sentra_users=""))

        assert _login(client).status_code == 503

    def test_and_me_says_there_is_no_session(self, client_with):
        client = client_with(_settings(session_secret=""))

        assert client.get("/api/me").status_code == 401


class TestTheCookie:
    def test_it_is_httponly_and_samesite(self, client_with):
        """HttpOnly so a script cannot read it, Lax so it does not ride along
        with a cross-site request."""
        client = client_with(_settings(session_cookie_secure=False))

        header = _login(client).headers["set-cookie"].lower()

        assert "httponly" in header
        assert "samesite=lax" in header

    def test_secure_is_set_when_asked_for(self, client_with):
        client = client_with(_settings(session_cookie_secure=True))

        assert "secure" in _login(client).headers["set-cookie"].lower()

    def test_and_the_default_is_on(self):
        """The one place the decision to ship a login before TLS is visible in
        code. An operator has to turn this off deliberately; defaulting it off
        would mean nobody ever noticed they were sending a session cookie in
        clear text."""
        assert Settings.model_fields["session_cookie_secure"].default is True


class TestPasswordStorage:
    def test_a_hash_does_not_contain_the_password(self):
        assert PASSWORT not in HASH

    def test_two_hashes_of_one_password_differ(self):
        """Salted. Otherwise the configuration leaks which people share a
        password."""
        assert hash_password(PASSWORT) != hash_password(PASSWORT)

    def test_a_malformed_hash_never_matches(self):
        """A configuration error must not be a way in."""
        assert verify_password(PASSWORT, UNLESBARER_EINTRAG) is False
        assert verify_password("", "") is False

    def test_a_malformed_user_entry_is_skipped_not_fatal(self):
        """The rest of the people should still be able to log in. A service
        that will not boot because one line is wrong is a service somebody
        switches off."""
        users = parse_users(f"gut:admin:{HASH}, kaputt, falscherang:xx:{HASH}")

        assert sorted(users) == ["gut"]


class TestRoleOrdering:
    def test_a_reviewer_is_at_least_a_reader(self):
        assert Subject("wd", PRUEFER).at_least(LESER)

    def test_but_not_an_admin(self):
        assert not Subject("wd", PRUEFER).at_least(ADMIN)

    def test_an_admin_is_everything(self):
        assert all(Subject("m", ADMIN).at_least(role) for role in (LESER, PRUEFER, ADMIN))
