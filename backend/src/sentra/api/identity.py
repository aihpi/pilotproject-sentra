"""Who the caller is. Not yet what they may do — that is api/auth.py.

A prototype login, and shaped throughout so that it is replaceable rather than
extendable. The IdP is not chosen (`references/SECURITY_NOTES.md`, Open), so
nothing here may depend on one: users come from configuration, and the only
thing the rest of the application is allowed to know is `current_subject()`,
which returns a name and a role. When the IdP is chosen, that function and
`/api/me` change and no endpoint does.

## Read this before deploying it

**This ships before TLS, deliberately, and the session cookie is the thing that
makes that a risk.** Today there is nothing to steal from a request; once
somebody logs in there is a cookie, and on a service published as a bare
LoadBalancer it crosses the network in clear text.

`session_cookie_secure` therefore defaults to **on**, and an operator has to
turn it off on purpose to run without TLS. Defaulting it off would be
convenient and would mean nobody ever noticed. See #161 item 1.

## What it is not

It is not authorisation, it is not an audit trail, and it is not protection
against somebody who can read the traffic. It answers "which of the people we
configured is this", well enough that a verdict has an author and the Admin tab
is not offered to everyone.
"""

import base64
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from sentra.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Roles, least to most. Ordered because "at least a reviewer" is the question
# every guard actually asks, and comparing names would spread that ordering
# across every call site.
LESER = "leser"
PRUEFER = "pruefer"
ADMIN = "admin"

ROLES: tuple[str, ...] = (LESER, PRUEFER, ADMIN)

# scrypt, at the parameters the Python docs call interactive-login grade. Not a
# new dependency, memory-hard, and it keeps the stored hash from being the weak
# link if the configuration leaks.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16


@dataclass(frozen=True)
class Subject:
    """The authenticated caller. The only shape the rest of the app sees."""

    name: str
    role: str

    def at_least(self, role: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)


def hash_password(password: str) -> str:
    """A storable hash: `scrypt.<salt>.<key>`, base64url without padding.

    **Dots and base64url, not `$` and standard base64.** The obvious format is
    `scrypt$salt$key`, and it does not survive the journey: docker compose
    performs variable substitution on the env file it is handed, so every `$`
    in a value is read as the start of a variable name and the salt and key
    vanish into empty strings. It then fails as a wrong password, which is a
    long way from the cause.

    base64url for the same class of reason — no `+` or `/` for something
    between here and the process to mangle — and the padding is stripped
    because `=` is the one character a shell might still argue with.

    Exposed because `python -m sentra.api.identity` uses it. Without a way to
    produce one, somebody stores a password in clear and means to fix it later.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt.{_encode(salt)}.{_encode(key)}"


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(text: str) -> bytes:
    # Padding back to a multiple of four, since hash_password strips it.
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify_password(password: str, stored: str) -> bool:
    """Whether the password matches, without leaking how it failed."""
    try:
        scheme, salt_b64, key_b64 = stored.split(".")
        if scheme != "scrypt":
            return False
        salt = _decode(salt_b64)
        expected = _decode(key_b64)
    except (ValueError, TypeError):
        # A malformed entry is a configuration error, not a login attempt. It
        # must not be a way in, and it must not crash the endpoint either.
        logger.warning("A configured password hash is malformed and cannot match.")
        return False

    actual = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return hmac.compare_digest(actual, expected)


def parse_users(raw: str) -> dict[str, tuple[str, str]]:
    """`name:role:hash` per line or comma, to {name: (role, hash)}.

    A flat string because it travels as one environment variable through a
    sealed secret, like everything else here. A malformed entry is skipped with
    a warning rather than refusing to start: the rest of the people should
    still be able to log in, and a service that will not boot because one line
    is wrong is a service somebody disables.
    """
    users: dict[str, tuple[str, str]] = {}
    for entry in raw.replace("\n", ",").split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 2)
        if len(parts) != 3:
            logger.warning("Ignoring a malformed SENTRA_USERS entry: expected name:role:hash")
            continue
        name, role, stored = (part.strip() for part in parts)
        if role not in ROLES:
            logger.warning("Ignoring user %r: role %r is not one of %s", name, role, ROLES)
            continue
        users[name] = (role, stored)
    return users


def authenticate(name: str, password: str, settings: Settings) -> Subject | None:
    """The configured user, if the password matches.

    An unknown user and a wrong password take the same path and the same time:
    the dummy hash below is verified against so that a missing user still costs
    a full scrypt derivation. Otherwise the endpoint answers "no such user"
    faster than "wrong password", which is a user-enumeration oracle whatever
    the message says.
    """
    users = parse_users(settings.sentra_users)
    found = users.get(name)
    stored = found[1] if found else _DUMMY_HASH
    matched = verify_password(password, stored)
    if found and matched:
        return Subject(name=name, role=found[0])
    return None


# Derived once at import, from a value nobody can log in with.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def login_configured(settings: Settings) -> bool:
    """Whether logging in is possible at all.

    Both halves are required. Without a signing secret a session cannot be
    issued; without users nobody could log in anyway. Absent means "no login",
    never a default key — a default signing key is a forged session for anyone
    who can read this repository.
    """
    return bool(settings.session_secret and settings.sentra_users)


def current_subject(request: Request, settings: Settings = Depends(get_settings)) -> Subject | None:
    """The caller, or None. **The seam.**

    Every guard reads identity through this and nothing reaches into the
    session directly. When the IdP arrives, this reads a verified token instead
    of a cookie and nothing above it changes.
    """
    if not login_configured(settings):
        return None
    data = request.session.get("subject")
    if not isinstance(data, dict):
        return None
    name, role = data.get("name"), data.get("role")
    if not isinstance(name, str) or role not in ROLES:
        return None
    return Subject(name=name, role=role)


def require_subject(subject: Subject | None = Depends(current_subject)) -> Subject:
    """A caller who is logged in, or 401."""
    if subject is None:
        raise HTTPException(status_code=401, detail="Anmeldung erforderlich.")
    return subject


def _main() -> None:
    """`uv run python -m sentra.api.identity` — print a hash for a password.

    Reads from a prompt rather than argv, so the password does not end up in
    the shell history of whoever set the pilot up.
    """
    import getpass

    password = getpass.getpass("Passwort: ")
    again = getpass.getpass("Wiederholen: ")
    if password != again:
        raise SystemExit("Die Eingaben stimmen nicht überein.")
    if not password:
        raise SystemExit("Ein leeres Passwort wird nicht gehasht.")
    print(hash_password(password))


if __name__ == "__main__":
    _main()
