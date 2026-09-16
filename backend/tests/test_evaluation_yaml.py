"""Cases as a file, both directions.

The property that carries the weight is idempotency. "The file is the source of
truth" is only true if applying it twice changes nothing the second time —
otherwise every import doubles the version history and the git diff stops
corresponding to what is in the database.

The second is that identity stays the backend's. A file can say what a case
contains; it cannot say which Test-ID it gets, because a hand-written ID is how
a number gets reused, which the Vorlage forbids outright.

In-memory SQLite: this is plain SQLAlchemy over the same models, and these
rules deserve to be checked on every CI run.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sentra.evaluation import cases as case_store
from sentra.evaluation import yaml_io
from sentra.evaluation.db import Base

ONE_CASE = """
- kategorie: GO
  ausgangsfrage: Wie lange darf ein Redner im Plenum sprechen?
  abteilung: Hotline
  erwartete_antwort: Grundsatz 15 Minuten je Fraktion nach § 35 GOBT.
  referenz_korrekt: GOBT § 35
  referenz_falsch: GOBT § 35 a. F. (vor der Novelle 2022)
"""


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _apply(session, text, **kwargs):
    return yaml_io.apply(session, yaml_io.parse(text), **kwargs)


# ── Reading ─────────────────────────────────────────────────────────


class TestParsing:
    def test_an_empty_file_is_no_cases(self):
        assert yaml_io.parse("") == []

    def test_a_mapping_at_the_top_is_refused_with_advice(self):
        with pytest.raises(yaml_io.CaseFileError, match="must be a list"):
            yaml_io.parse("kategorie: GO")

    def test_broken_yaml_says_so(self):
        with pytest.raises(yaml_io.CaseFileError, match="not valid YAML"):
            yaml_io.parse("- kategorie: [unclosed")

    def test_a_problem_names_the_case_and_the_field(self):
        """Whoever wrote the file wrote YAML, so they are told which case and
        which key — not about `loc` and `input_value`."""
        text = "- test_id: TF-GO-007\n  kategorie: ZZ\n  ausgangsfrage: x\n"

        with pytest.raises(yaml_io.CaseFileError) as caught:
            yaml_io.parse(text)

        assert "TF-GO-007" in str(caught.value)
        assert "kategorie" in str(caught.value)

    def test_a_case_without_a_test_id_is_named_by_position(self):
        with pytest.raises(yaml_io.CaseFileError, match="entry 1"):
            yaml_io.parse("- kategorie: GO\n")  # no ausgangsfrage


# ── Importing ───────────────────────────────────────────────────────


class TestImporting:
    def test_a_case_without_a_test_id_gets_one(self, session):
        report = _apply(session, ONE_CASE)

        assert report.created == ["TF-GO-001"]

    def test_importing_twice_changes_nothing(self, session):
        """The property that makes the file a source of truth."""
        _apply(session, ONE_CASE)

        report = _apply(session, yaml_io.dump(session))

        assert report.created == []
        assert report.updated == []
        assert report.unchanged == ["TF-GO-001"]

    def test_and_does_not_add_a_version(self, session):
        _apply(session, ONE_CASE)
        _apply(session, yaml_io.dump(session))

        case = case_store.get_case(session, "TF-GO-001")
        assert len(case.versions) == 1

    def test_changed_content_edits_a_draft_in_place(self, session):
        _apply(session, ONE_CASE)
        changed = yaml_io.dump(session).replace("15 Minuten", "20 Minuten")

        report = _apply(session, changed)

        case = case_store.get_case(session, "TF-GO-001")
        assert report.updated == ["TF-GO-001"]
        assert len(case.versions) == 1

    def test_changed_content_versions_an_approved_case(self, session):
        _apply(session, ONE_CASE + "  status: freigegeben\n")
        changed = yaml_io.dump(session).replace("15 Minuten", "20 Minuten")

        _apply(session, changed)

        case = case_store.get_case(session, "TF-GO-001")
        assert [v.version for v in case.versions] == [1, 2]
        assert case.versions[0].erwartete_antwort.count("15 Minuten") == 1

    def test_status_freigegeben_approves(self, session):
        report = _apply(session, ONE_CASE + "  status: freigegeben\n")

        assert report.approved == ["TF-GO-001"]
        assert case_store.latest_approved(case_store.get_case(session, "TF-GO-001")) is not None

    def test_an_incomplete_case_cannot_be_approved_from_a_file(self, session):
        text = "- kategorie: GO\n  ausgangsfrage: x\n  status: freigegeben\n"

        with pytest.raises(yaml_io.CaseFileError, match="erwartete Antwort"):
            _apply(session, text)


# ── Identity stays the backend's ────────────────────────────────────


class TestIdentity:
    def test_an_unknown_test_id_is_refused(self, session):
        text = ONE_CASE.replace("- kategorie: GO", "- test_id: TF-GO-042\n  kategorie: GO")

        with pytest.raises(yaml_io.CaseFileError, match="allocated by the backend"):
            _apply(session, text)

    def test_seeding_is_possible_but_must_be_asked_for(self, session):
        text = ONE_CASE.replace("- kategorie: GO", "- test_id: TF-GO-042\n  kategorie: GO")

        report = _apply(session, text, allow_new_ids=True)

        assert report.created == ["TF-GO-042"]

    def test_seeding_advances_the_counter_past_the_number(self, session):
        """Otherwise seeding TF-GO-042 and then creating a case normally would
        produce a second TF-GO-042 — the exact failure the allocator exists to
        prevent."""
        text = ONE_CASE.replace("- kategorie: GO", "- test_id: TF-GO-042\n  kategorie: GO")
        _apply(session, text, allow_new_ids=True)

        report = _apply(session, ONE_CASE)

        assert report.created == ["TF-GO-043"]

    def test_a_malformed_seeded_id_is_refused(self, session):
        text = ONE_CASE.replace("- kategorie: GO", "- test_id: GO-42\n  kategorie: GO")

        with pytest.raises(case_store.CaseError, match="not a Test-ID"):
            _apply(session, text, allow_new_ids=True)

    def test_a_seeded_id_must_match_its_category(self, session):
        text = ONE_CASE.replace("- kategorie: GO", "- test_id: TF-GV-001\n  kategorie: GO")

        with pytest.raises(case_store.CaseError, match="not a Test-ID for category GO"):
            _apply(session, text, allow_new_ids=True)


# ── Round trip ──────────────────────────────────────────────────────


class TestRoundTrip:
    def test_export_reimports_to_the_same_versions(self, session):
        _apply(session, ONE_CASE + "  status: freigegeben\n")
        before = yaml_io.dump(session)

        _apply(session, before)

        assert yaml_io.dump(session) == before

    def test_german_survives_the_round_trip(self, session):
        """allow_unicode, so a reviewer reads § and ä rather than escapes."""
        _apply(session, ONE_CASE)

        text = yaml_io.dump(session)

        assert "§ 35" in text
        assert "\\u" not in text

    def test_withdrawn_cases_are_left_out_by_default(self, session):
        _apply(session, ONE_CASE)
        case_store.withdraw(session, case_store.get_case(session, "TF-GO-001"))

        assert yaml_io.parse(yaml_io.dump(session)) == []
        assert len(yaml_io.parse(yaml_io.dump(session, include_withdrawn=True))) == 1


# ── The CLI ─────────────────────────────────────────────────────────


class TestTheCli:
    """End to end through the entry point an operator actually runs."""

    @pytest.fixture
    def cli(self, monkeypatch, tmp_path):
        from sentra.evaluation.config import get_eval_settings
        from sentra.evaluation.db import Base as DbBase
        from sentra.evaluation.db import get_engine

        monkeypatch.setenv("EVAL_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'cli.db'}")
        get_eval_settings.cache_clear()
        get_engine.cache_clear()
        DbBase.metadata.create_all(get_engine())

        from sentra.evaluation.cli import main

        yield main
        get_eval_settings.cache_clear()
        get_engine.cache_clear()

    def test_import_then_export_round_trips(self, cli, tmp_path):
        source = tmp_path / "cases.yaml"
        source.write_text(ONE_CASE, encoding="utf-8")
        assert cli(["import", str(source)]) == 0

        exported = tmp_path / "out.yaml"
        assert cli(["export", str(exported)]) == 0

        assert "TF-GO-001" in exported.read_text(encoding="utf-8")

    def test_a_dry_run_writes_nothing(self, cli, tmp_path, capsys):
        source = tmp_path / "cases.yaml"
        source.write_text(ONE_CASE, encoding="utf-8")

        assert cli(["import", str(source), "--dry-run"]) == 0

        exported = tmp_path / "out.yaml"
        cli(["export", str(exported)])
        assert exported.read_text(encoding="utf-8").strip() in ("[]", "")

    def test_a_bad_file_exits_nonzero_and_says_why(self, cli, tmp_path, capsys):
        source = tmp_path / "cases.yaml"
        source.write_text("- kategorie: ZZ\n  ausgangsfrage: x\n", encoding="utf-8")

        assert cli(["import", str(source)]) == 1
        assert "kategorie" in capsys.readouterr().err

    def test_the_example_file_in_the_repository_is_valid(self, cli):
        """The file that documents the format has to be a file that works."""
        from pathlib import Path

        example = Path(__file__).resolve().parents[1] / "eval_cases" / "beispiel.yaml"

        assert cli(["import", str(example)]) == 0
