"""The user table, and the rules that keep an installation administrable.

Users lived only in `SENTRA_USERS` until now, which made adding a colleague a
deployment: hash a password on a developer's machine, edit a sealed secret,
restart. Nobody does that for the third reviewer, so the pilot ends up with
shared logins — which destroys the one thing the login was for, an author on a
verdict.

**Configuration becomes a bootstrap rather than the store.** `SENTRA_USERS`
still works and has to: it is how the first admin exists on a fresh
installation, before anybody can log in to create one. A user in the database
wins over a configured one of the same name, because otherwise a password
changed in the UI would be silently undone by whatever is in the environment.

**This is still the prototype login.** A local user table is not an identity
provider. When the IdP arrives this becomes either a fallback or history, so
nothing should build a permissions system on top of it —
`references/SECURITY_NOTES.md` item 2.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from sentra.api.identity import ADMIN, ROLES, Subject, hash_password
from sentra.config import Settings
from sentra.db import Base


class LastAdmin(RuntimeError):
    """Refused: it would leave the installation with no administrator."""


class Self(RuntimeError):
    """Refused: an admin removing or demoting themselves."""


class UnknownUser(RuntimeError):
    """No such user."""


class DuplicateUser(RuntimeError):
    """That name is taken."""


class User(Base):
    """One person who can sign in.

    The password is the same `scrypt.<salt>.<key>` the login already verifies —
    one format, one verifier, so a user created here and one configured in the
    environment are checked by the same code.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # Never returned by any endpoint and never logged. The column exists so the
    # verifier has something to compare against; nothing else may read it.
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


def list_users(session: Session) -> list[User]:
    return list(session.execute(select(User).order_by(User.name)).scalars())


def _admin_count(session: Session) -> int:
    return len(session.execute(select(User.id).where(User.role == ADMIN)).scalars().all())


def create_user(session: Session, *, name: str, role: str, password: str) -> User:
    name = name.strip()
    if not name:
        raise ValueError("Ein Benutzername darf nicht leer sein.")
    if role not in ROLES:
        raise ValueError(f"Unbekannte Rolle: {role}")
    if not password:
        raise ValueError("Ein leeres Passwort wird nicht gesetzt.")
    if session.execute(select(User).where(User.name == name)).scalar_one_or_none():
        raise DuplicateUser(f"Der Benutzername „{name}“ ist bereits vergeben.")

    user = User(name=name, role=role, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def update_user(
    session: Session,
    name: str,
    *,
    acting: Subject | None,
    role: str | None = None,
    password: str | None = None,
) -> User:
    """Change a role, a password, or both.

    Demoting the last admin is refused, and so is demoting yourself. They are
    different mistakes — the first is reached by tidying up, the second by
    clicking the wrong row — and an installation with no administrator is
    recoverable only by editing the database by hand.
    """
    user = _lookup(session, name)

    if role is not None:
        if role not in ROLES:
            raise ValueError(f"Unbekannte Rolle: {role}")
        if user.role == ADMIN and role != ADMIN:
            if acting is not None and acting.name == user.name:
                raise Self("Die eigene Administratorrolle kann nicht entzogen werden.")
            if _admin_count(session) <= 1:
                raise LastAdmin("Das ist der letzte Administrator. Erst einen weiteren anlegen.")
        user.role = role

    if password is not None:
        if not password:
            raise ValueError("Ein leeres Passwort wird nicht gesetzt.")
        user.password_hash = hash_password(password)

    session.flush()
    return user


def delete_user(session: Session, name: str, *, acting: Subject | None) -> None:
    user = _lookup(session, name)

    if acting is not None and acting.name == user.name:
        raise Self("Das eigene Konto kann nicht gelöscht werden.")
    if user.role == ADMIN and _admin_count(session) <= 1:
        raise LastAdmin("Das ist der letzte Administrator. Erst einen weiteren anlegen.")

    session.delete(user)
    session.flush()


def _lookup(session: Session, name: str) -> User:
    user = session.execute(select(User).where(User.name == name)).scalar_one_or_none()
    if user is None:
        raise UnknownUser(f"Kein Benutzer mit dem Namen „{name}“.")
    return user


def stored_credentials(session: Session, name: str) -> tuple[str, str] | None:
    """`(role, hash)` for a database user, or None.

    The database is consulted before configuration, so a password changed in
    the UI is not silently undone by whatever is still in the environment.
    """
    user = session.execute(select(User).where(User.name == name)).scalar_one_or_none()
    return (user.role, user.password_hash) if user else None


def bootstrap_note(settings: Settings) -> str:
    """Whether configured users are still in play, for /api/health.

    Not cosmetic: an operator wondering why an account they deleted can still
    log in is looking at a name that is also in SENTRA_USERS.
    """
    return "konfiguriert + Datenbank" if settings.sentra_users else "Datenbank"
