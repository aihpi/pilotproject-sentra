"""The one gate in front of writing and in front of personal data.

**This is not identity, and nothing here should be read as identity.** It
answers "was this caller given the secret" and nothing else — not who they are,
not what they may do beyond the endpoints that depend on it. `Verdict.tester`
stays a name somebody types until there is a subject to derive it from. See
`references/SECURITY_NOTES.md`, item 9.

It exists because two paths had nothing in front of them at all, on a service
published as a bare LoadBalancer:

    POST /api/ingest    re-indexes the corpus WD reads as authoritative
    GET  /api/feedback  user-typed questions — personal data under DSGVO

Both are fixed by the backend refusing, which is the part a login would not
have provided anyway: a hidden tab hides a button, not an endpoint.

One dependency, deliberately, so that replacing a shared secret with signature
verification against the IdP's JWKS is a change here and nowhere else.

## Why it is off when unset, and why that is reported

A pilot that answers 401 to everything the moment it is updated is a pilot that
gets rolled back, and a developer running compose should not need a secret to
start. So an unset token means the endpoints stay open.

That is a real weakening and it is not left silent. The state appears on
`/api/health`, which is a thing somebody looks at, rather than only in a log
line on a pod nobody tails. A control that is switched off while reading as
protection is worse than no control.
"""

import logging
import secrets

from fastapi import Depends, Header, HTTPException

from sentra.config import Settings, get_settings

logger = logging.getLogger(__name__)

OPEN = "offen"
PROTECTED = "token"


def write_paths_state(settings: Settings) -> str:
    """Whether the guarded paths are guarded. Reported by /api/health."""
    return PROTECTED if settings.admin_token else OPEN


def warn_if_open(settings: Settings) -> None:
    """Say so at startup, once, where an operator will see it."""
    if not settings.admin_token:
        logger.warning(
            "ADMIN_TOKEN is not set: POST /api/ingest and GET /api/feedback are open to "
            "any caller that can reach this service. GET /api/health reports this as "
            "auth='%s'.",
            OPEN,
        )


def require_token(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Refuse a caller without the token, when a token is configured.

    Two headers because two kinds of caller. `Authorization: Bearer` is what
    the harness and anything else speaking HTTP will reach for; `X-Admin-Token`
    is easier to set from a browser fetch without colliding with whatever an
    eventual login puts in Authorization.

    `compare_digest` rather than `==`: it is one line, and the alternative is a
    timing oracle on the only secret in the system.
    """
    expected = settings.admin_token
    if not expected:
        return

    offered = x_admin_token
    if offered is None and authorization and authorization.lower().startswith("bearer "):
        offered = authorization[len("bearer ") :].strip()

    if offered is None or not secrets.compare_digest(offered, expected):
        # 401 rather than 403: the caller may well be allowed, they have simply
        # not said who they are. And no detail about which header was wrong —
        # that is only useful to somebody guessing.
        raise HTTPException(
            status_code=401,
            detail="Für diesen Zugriff ist ein Token erforderlich.",
            headers={"WWW-Authenticate": "Bearer"},
        )
