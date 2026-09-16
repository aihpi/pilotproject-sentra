"""The case store, and the rule the whole harness rests on.

The Vorlage requires the expected answer to be "formuliert bevor SENTRA
getestet wird, damit die Erwartung nicht nachträglich an die tatsächliche
Ausgabe angepasst wird". That is not something people can be asked to remember
while looking at a disappointing answer, so the store has to make it true:

  - a draft is editable, because writing a case is iterative and nothing has
    been measured against it
  - approving stamps freigegeben_at and closes the version for good
  - "editing" an approved case adds a new version; the old one stays exactly as
    it was, so a run that referenced it still points at what it measured against

And the Test-ID rule: allocated by the backend, never reused, "auch bei
zurückgezogenen Testfällen nicht".

These run against SQLite in memory rather than Postgres. The store is plain
SQLAlchemy with no Postgres-specific types, the schema comes from the same
models, and keeping them offline means the rules above are checked on every CI
run rather than only when somebody has compose up. The migrations themselves
are covered against real Postgres in test_evaluation_migrations.py.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sentra.evaluation import cases as case_store
from sentra.evaluation.categories import Kategorie
from sentra.evaluation.db import Base
from sentra.evaluation.models import ENTWURF, FREIGEGEBEN


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _complete_case(session, kategorie=Kategorie.GO, **overrides):
    fields = {
        "ausgangsfrage": "Wie lange darf ein Redner im Plenum sprechen?",
        "abteilung": "Hotline",
        "erwartete_antwort": "Grundsatz 15 Minuten je Fraktion nach § 35 GOBT.",
        "referenz_korrekt": "GOBT § 35",
        "referenz_falsch": "GOBT § 35 a. F. (vor der Novelle 2022)",
    }
    fields.update(overrides)
    return case_store.create_case(session, kategorie=kategorie, **fields)


# ── Test-IDs ────────────────────────────────────────────────────────


class TestTestIdAllocation:
    def test_the_first_case_in_a_category_is_001(self, session):
        case, _ = _complete_case(session)

        assert case.test_id == "TF-GO-001"

    def test_numbers_run_consecutively_within_a_category(self, session):
        ids = [_complete_case(session)[0].test_id for _ in range(3)]

        assert ids == ["TF-GO-001", "TF-GO-002", "TF-GO-003"]

    def test_categories_count_separately(self, session):
        _complete_case(session, Kategorie.GO)
        case, _ = _complete_case(session, Kategorie.GV)

        assert case.test_id == "TF-GV-001"

    def test_a_withdrawn_case_does_not_free_its_number(self, session):
        """The Vorlage's "auch bei zurückgezogenen Testfällen nicht".

        A max(number) + 1 allocator passes every test above and fails this one,
        which is the entire reason there is a counter table.
        """
        first, _ = _complete_case(session)
        case_store.withdraw(session, first)

        next_case, _ = _complete_case(session)

        assert next_case.test_id == "TF-GO-002"
        assert first.test_id == "TF-GO-001"

    def test_the_caller_cannot_choose_one(self, session):
        """create_case takes no test_id argument at all — the guarantee is that
        there is no way to ask for a specific number, not that asking is
        rejected."""
        import inspect

        assert "test_id" not in inspect.signature(case_store.create_case).parameters


# ── Drafts are editable ─────────────────────────────────────────────


class TestDrafts:
    def test_a_new_case_starts_as_a_draft(self, session):
        _, version = _complete_case(session)

        assert version.status == ENTWURF
        assert version.freigegeben_at is None

    def test_a_complete_case_is_still_a_draft(self, session):
        """Approval is a separate act with its own timestamp. Collapsing the two
        would lose the difference between "approved" and "nobody looked"."""
        _, version = _complete_case(session)

        assert version.status == ENTWURF

    def test_a_draft_can_be_edited_in_place(self, session):
        _, version = _complete_case(session)

        case_store.edit_draft(session, version, erwartete_antwort="Etwas anderes")

        assert version.erwartete_antwort == "Etwas anderes"
        assert version.version == 1


# ── Approval closes the version ─────────────────────────────────────


class TestApproval:
    def test_approving_stamps_the_audit_timestamp(self, session):
        _, version = _complete_case(session)

        case_store.approve(session, version)

        assert version.status == FREIGEGEBEN
        assert version.freigegeben_at is not None

    def test_an_approved_version_cannot_be_edited(self, session):
        """The rule everything else rests on."""
        _, version = _complete_case(session)
        case_store.approve(session, version)

        with pytest.raises(case_store.ApprovedVersionIsImmutable):
            case_store.edit_draft(session, version, erwartete_antwort="nachträglich angepasst")

    def test_without_an_expected_answer_it_cannot_be_approved(self, session):
        _, version = _complete_case(session, erwartete_antwort="")

        with pytest.raises(case_store.IncompleteCase, match="erwartete Antwort"):
            case_store.approve(session, version)

    def test_without_a_correct_reference_it_cannot_be_approved(self, session):
        _, version = _complete_case(session, referenz_korrekt="")

        with pytest.raises(case_store.IncompleteCase, match="Referenzquelle"):
            case_store.approve(session, version)

    def test_the_message_names_everything_missing_at_once(self, session):
        _, version = _complete_case(session, erwartete_antwort="", referenz_korrekt="")

        with pytest.raises(case_store.IncompleteCase) as caught:
            case_store.approve(session, version)

        assert "erwartete Antwort" in str(caught.value)
        assert "Referenzquelle" in str(caught.value)


# ── Editing an approved case adds a version ─────────────────────────


class TestVersions:
    def test_a_new_version_starts_from_the_previous_content(self, session):
        case, first = _complete_case(session)
        case_store.approve(session, first)

        second = case_store.add_version(session, case, erwartete_antwort="Überarbeitet")

        assert second.version == 2
        assert second.erwartete_antwort == "Überarbeitet"
        assert second.referenz_korrekt == first.referenz_korrekt  # carried over

    def test_the_old_version_is_untouched(self, session):
        """What a finished round was measured against has to stay readable
        exactly as it was, or a reported result cannot be checked later."""
        case, first = _complete_case(session)
        case_store.approve(session, first)
        original = first.erwartete_antwort

        case_store.add_version(session, case, erwartete_antwort="Überarbeitet")

        assert first.erwartete_antwort == original
        assert first.status == FREIGEGEBEN

    def test_a_new_version_is_a_draft(self, session):
        case, first = _complete_case(session)
        case_store.approve(session, first)

        second = case_store.add_version(session, case, erwartete_antwort="Überarbeitet")

        assert second.status == ENTWURF

    def test_runs_use_the_latest_approved_not_the_latest(self, session):
        """A draft for the next round must not change what this round measures."""
        case, first = _complete_case(session)
        case_store.approve(session, first)
        case_store.add_version(session, case, erwartete_antwort="noch nicht freigegeben")

        assert case_store.latest_approved(case) is first

    def test_a_case_with_no_approved_version_is_not_runnable(self, session):
        case, _ = _complete_case(session)

        assert case_store.latest_approved(case) is None


# ── Reading ─────────────────────────────────────────────────────────


class TestReading:
    def test_withdrawn_cases_are_hidden_by_default(self, session):
        first, _ = _complete_case(session)
        _complete_case(session)
        case_store.withdraw(session, first)

        assert [c.test_id for c in case_store.list_cases(session)] == ["TF-GO-002"]

    def test_withdrawn_cases_can_still_be_read(self, session):
        """A round that referenced one has to stay explicable afterwards."""
        first, _ = _complete_case(session)
        case_store.withdraw(session, first)

        assert case_store.get_case(session, first.test_id).zurueckgezogen_at is not None

    def test_an_unknown_test_id_is_its_own_error(self, session):
        with pytest.raises(case_store.UnknownCase, match="TF-GO-999"):
            case_store.get_case(session, "TF-GO-999")
