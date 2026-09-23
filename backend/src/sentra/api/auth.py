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
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException

from sentra.api.identity import Subject, current_subject, login_configured
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


def has_token(
    authorization: str | None,
    x_admin_token: str | None,
    settings: Settings,
) -> bool:
    """Whether this request carried the machine token.

    Split out of the guard so a role check can ask the same question. A machine
    caller has no session to offer — the evaluation harness reads feedback over
    HTTP like any other client — so the token is how it gets through, and it
    grants the guarded endpoints outright rather than carrying a role. A shared
    secret cannot identify anybody, which is the whole reason the login exists.
    """
    expected = settings.admin_token
    if not expected:
        return False

    offered = x_admin_token
    if offered is None and authorization and authorization.lower().startswith("bearer "):
        offered = authorization[len("bearer ") :].strip()

    return offered is not None and secrets.compare_digest(offered, expected)


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
    if not settings.admin_token:
        return

    if not has_token(authorization, x_admin_token, settings):
        # 401 rather than 403: the caller may well be allowed, they have simply
        # not said who they are. And no detail about which header was wrong —
        # that is only useful to somebody guessing.
        raise HTTPException(
            status_code=401,
            detail="Für diesen Zugriff ist ein Token erforderlich.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Roles ───────────────────────────────────────────────────────────


def require_role(minimum: str) -> Callable[..., Subject | None]:
    """A caller of at least `minimum`, or the machine token, or nothing.

    Three ways past this, and they are not the same thing:

      a session of sufficient rank   a person, and we know which
      the machine token             a caller that was handed the secret. No
                                    identity, and deliberately blunt — see
                                    has_token
      neither configured            open, as it was before any of this, and
                                    reported by /api/health

    **401 and 403 are different answers.** 401 means "say who you are", which a
    browser can act on by offering a login. 403 means "I know who you are and
    the answer is still no", which it must not answer by asking them to log in
    again — that is a loop, and an infuriating one.

    Returns the Subject when there was one, so an endpoint that wants to record
    who acted can take it. `None` means the caller came through as a machine or
    through an unguarded deployment, and an endpoint that needs a name has to
    say so itself rather than assume.
    """

    def guard(
        subject: Subject | None = Depends(current_subject),
        authorization: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
        settings: Settings = Depends(get_settings),
    ) -> Subject | None:
        if has_token(authorization, x_admin_token, settings):
            return subject

        if subject is not None:
            if subject.at_least(minimum):
                return subject
            raise HTTPException(
                status_code=403,
                detail=f"Diese Aktion erfordert mindestens die Rolle „{minimum}“.",
            )

        # No session and no token. Open only if nothing is configured to check
        # against — the same trade as #162, for the same reason, and reported
        # in the same place.
        if not settings.admin_token and not login_configured(settings):
            return None

        raise HTTPException(
            status_code=401,
            detail="Für diesen Zugriff ist eine Anmeldung erforderlich.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return guard
