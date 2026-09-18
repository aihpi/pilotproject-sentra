"""Administering users, and the two rules that keep an installation usable.

Against SQLite in memory: the store is plain SQLAlchemy and the rules are about
the user set rather than about Postgres. The migration that builds this on a
real server is covered with the rest of the chain.

**The two lockout guards are the point of this module.** An installation with
no administrator is recoverable only by editing the database by hand, and they
are two different mistakes:

    the last admin      reached by tidying up — removing an account that looks
                        redundant, on a Friday
    yourself            reached by clicking the wrong row

Either one alone leaves the other open, which is why both are tested from both
directions: refused when it would lock the door, allowed when it would not.
"""

import secrets

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sentra.api import users as user_store
from sentra.api.identity import ADMIN, LESER, PRUEFER, Subject, verify_password
from sentra.db import Base

PASSWORT = secrets.token_urlsafe(16)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _admin(session, name="chef"):
    return user_store.create_user(session, name=name, role=ADMIN, password=PASSWORT)


def _reader(session, name="gast"):
    return user_store.create_user(session, name=name, role=LESER, password=PASSWORT)


class TestCreating:
    def test_a_user_can_sign_in_with_the_password_set(self, session):
        """One hash format and one verifier, so a user created here and one
        configured in the environment are checked by the same code."""
        user = _admin(session)

        assert verify_password(PASSWORT, user.password_hash)

    def test_the_password_is_not_stored_as_given(self, session):
        user = _admin(session)

        assert PASSWORT not in user.password_hash

    def test_a_duplicate_name_is_refused(self, session):
        _admin(session)

        with pytest.raises(user_store.DuplicateUser):
            _admin(session)

    def test_an_unknown_role_is_refused(self, session):
        with pytest.raises(ValueError, match="Rolle"):
            user_store.create_user(session, name="x", role="chefchef", password=PASSWORT)

    def test_an_empty_password_is_refused(self, session):
        """Otherwise the account exists and nobody can say what its password
        is, including whoever created it."""
        with pytest.raises(ValueError):
            user_store.create_user(session, name="x", role=LESER, password="")


class TestTheLastAdmin:
    def test_cannot_be_deleted(self, session):
        _admin(session)
        _reader(session)

        with pytest.raises(user_store.LastAdmin):
            user_store.delete_user(session, "chef", acting=Subject("wer", ADMIN))

    def test_cannot_be_demoted(self, session):
        _admin(session)

        with pytest.raises(user_store.LastAdmin):
            user_store.update_user(session, "chef", acting=Subject("wer", ADMIN), role=PRUEFER)

    def test_but_a_second_admin_makes_either_possible(self, session):
        _admin(session, "chef")
        _admin(session, "vertretung")

        user_store.delete_user(session, "chef", acting=Subject("vertretung", ADMIN))

        assert [u.name for u in user_store.list_users(session)] == ["vertretung"]

    def test_and_a_non_admin_is_never_the_last_admin(self, session):
        _admin(session)
        _reader(session)

        user_store.delete_user(session, "gast", acting=Subject("chef", ADMIN))

        assert [u.name for u in user_store.list_users(session)] == ["chef"]


class TestYourself:
    def test_cannot_be_deleted(self, session):
        _admin(session, "chef")
        _admin(session, "vertretung")

        with pytest.raises(user_store.Self):
            user_store.delete_user(session, "chef", acting=Subject("chef", ADMIN))

    def test_cannot_be_demoted(self, session):
        _admin(session, "chef")
        _admin(session, "vertretung")

        with pytest.raises(user_store.Self):
            user_store.update_user(session, "chef", acting=Subject("chef", ADMIN), role=LESER)

    def test_even_though_another_admin_exists(self, session):
        """The distinction from the last-admin rule. This one is not about
        leaving the installation unadministrable — it is about locking
        yourself out of a door somebody else can still open, which is its own
        bad afternoon."""
        _admin(session, "chef")
        _admin(session, "vertretung")
        _admin(session, "dritte")

        with pytest.raises(user_store.Self):
            user_store.delete_user(session, "chef", acting=Subject("chef", ADMIN))

    def test_but_your_own_password_can_be_changed(self, session):
        """Changing your own password is not a lockout, it is the ordinary
        reason to open this screen."""
        _admin(session, "chef")
        neu = secrets.token_urlsafe(16)

        user = user_store.update_user(session, "chef", acting=Subject("chef", ADMIN), password=neu)

        assert verify_password(neu, user.password_hash)


class TestChanging:
    def test_a_role_without_resending_a_password(self, session):
        _admin(session)
        _reader(session)
        before = user_store._lookup(session, "gast").password_hash

        user_store.update_user(session, "gast", acting=Subject("chef", ADMIN), role=PRUEFER)

        assert user_store._lookup(session, "gast").role == PRUEFER
        assert user_store._lookup(session, "gast").password_hash == before

    def test_a_password_without_restating_the_role(self, session):
        _admin(session)
        _reader(session)
        neu = secrets.token_urlsafe(16)

        user_store.update_user(session, "gast", acting=Subject("chef", ADMIN), password=neu)

        assert user_store._lookup(session, "gast").role == LESER
        assert verify_password(neu, user_store._lookup(session, "gast").password_hash)

    def test_an_unknown_user_is_not_a_silent_no_op(self, session):
        with pytest.raises(user_store.UnknownUser):
            user_store.update_user(session, "niemand", acting=None, role=LESER)


class TestPrecedenceOverConfiguration:
    def test_the_database_answers_for_a_name_it_holds(self, session):
        """A password changed in the UI must not be undone by whatever is still
        in SENTRA_USERS — that is precedence discovered during an incident."""
        _admin(session, "chef")

        found = user_store.stored_credentials(session, "chef")

        assert found is not None
        assert found[0] == ADMIN

    def test_and_says_nothing_about_a_name_it_does_not(self, session):
        """So configuration can still answer, which is how the first admin
        exists before anybody can sign in to create one."""
        assert user_store.stored_credentials(session, "konfiguriert") is None
