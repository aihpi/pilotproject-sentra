"""The collection templates, and the round trip through them.

A round is only as good as its cases, and the cases come from people who will
not be editing YAML. So the sheet they fill in has to arrive in the database
meaning what they wrote — which is two claims, tested separately:

  the columns are the importer's fields      test_fields_match_the_importer
  a filled sheet reads back as those cases   TestReadingAFilledSheet

The first is the one that rots. A spreadsheet whose columns have quietly
drifted from `CaseEntry` is worse than no spreadsheet, because the drift is
found by somebody who has already filled in two hundred rows.

The first claim needs no spreadsheet library at all, so it runs everywhere,
including where `--extra vorlagen` was not installed. Only the tests that build
or read a file skip there.
"""

from pathlib import Path

import pytest

from sentra_eval import vorlagen, yaml_io
from sentra_eval.categories import Kategorie
from sentra_eval.yaml_io import CaseEntry


def test_fields_match_the_importer():
    """Every collected field is one the importer accepts, and every field the
    importer needs is collected.

    `test_id` and `status` are excluded deliberately, not forgotten: the
    backend allocates the one and never reuses it, and approval is a review
    decision rather than the author's.
    """
    importable = set(CaseEntry.model_fields) - {"test_id", "status"}

    assert set(vorlagen.FIELD_NAMES) == importable


def test_the_required_fields_are_the_ones_a_case_cannot_do_without():
    pflicht = {f.name for f in vorlagen.FIELDS if f.pflicht}

    assert pflicht == {"kategorie", "ausgangsfrage", "erwartete_antwort"}


def test_every_field_explains_itself():
    """The help text is the template. A column called "Referenzquelle (korrekt)"
    with no explanation gets filled in with a guess."""
    assert all(len(f.hilfe) > 40 for f in vorlagen.FIELDS)


# Only the tests that build or read a file need the packages. The three above
# compare `FIELDS` against the importer and against itself, which is the
# guarantee that rots, so they must run everywhere — including where the extra
# is not installed.
openpyxl = pytest.importorskip("openpyxl", reason="needs `uv sync --extra vorlagen`")


class TestTheWorkbook:
    def test_it_has_a_sheet_to_fill_and_a_sheet_that_explains(self, tmp_path):
        path = tmp_path / "v.xlsx"
        vorlagen.build_workbook().save(path)

        book = openpyxl.load_workbook(path)

        assert book.sheetnames == ["Testfälle", "Ausfüllhinweise"]

    def test_the_header_is_the_field_labels(self, tmp_path):
        path = tmp_path / "v.xlsx"
        vorlagen.build_workbook().save(path)

        sheet = openpyxl.load_workbook(path)["Testfälle"]
        header = [str(c.value).replace(" *", "") for c in sheet[1]]

        assert header == [f.label for f in vorlagen.FIELDS]

    def test_the_categories_are_a_dropdown(self, tmp_path):
        """`kategorie` decides the Test-ID, so a typo is a case that cannot be
        imported at all."""
        path = tmp_path / "v.xlsx"
        vorlagen.build_workbook().save(path)

        sheet = openpyxl.load_workbook(path)["Testfälle"]
        formulas = [v.formula1 for v in sheet.data_validations.dataValidation]

        assert any(all(k.value in f for k in Kategorie) for f in formulas)


class TestTheWordForm:
    def test_it_is_a_form_rather_than_a_document_to_type_over(self, tmp_path):
        """Real content controls, so it can be tabbed through and the guidance
        is not something to accidentally overwrite."""
        pytest.importorskip("docx", reason="needs `uv sync --extra vorlagen`")
        import zipfile

        path = tmp_path / "v.docx"
        vorlagen.build_document().save(path)

        xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")

        assert xml.count("<w:sdt>") == len(vorlagen.FIELDS)
        assert "dropDownList" in xml

    def test_each_control_is_tagged_with_its_field_name(self, tmp_path):
        """So a returned form can be read back by machine later, rather than
        only by eye."""
        pytest.importorskip("docx", reason="needs `uv sync --extra vorlagen`")
        import zipfile

        path = tmp_path / "v.docx"
        vorlagen.build_document().save(path)
        xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")

        for feld in vorlagen.FIELDS:
            assert f'w:val="{feld.name}"' in xml


def _filled(tmp_path: Path, rows: list[dict]) -> Path:
    """A template filled in the way a person would fill it: by label."""
    path = tmp_path / "filled.xlsx"
    book = vorlagen.build_workbook()
    sheet = book["Testfälle"]
    columns = {f.label: index for index, f in enumerate(vorlagen.FIELDS, start=1)}
    for offset, row in enumerate(rows, start=2):
        for label, value in row.items():
            sheet.cell(row=offset, column=columns[label], value=value)
    book.save(path)
    return path


ORDENTLICH = {
    "Kategorie": "GO",
    "Ausgangsfrage": "Wie lange darf ein Redner im Plenum sprechen?",
    "Abteilung / Fachbereich": "Hotline",
    "Erwartete Antwort": "15 Minuten je Fraktion nach § 35 GOBT.",
    "Korrekte Quelle": "GOBT § 35",
    "Aktenzeichen der korrekten Quelle": "WD 3 - 3000 - 029/23",
    "Grund für die Aufnahme": "Häufigste Frage der Hotline.",
    "Grenzfall?": "nein",
}

GRENZFALL = {
    "Kategorie": "AR",
    "Ausgangsfrage": "Wie hoch ist die Mondtagegeldpauschale zum Mars?",
    "Erwartete Antwort": "Keine Antwort. Der Bestand enthält nichts dazu.",
    "Grenzfall?": "ja",
}


class TestReadingAFilledSheet:
    def test_a_filled_row_becomes_a_case(self, tmp_path):
        entries = yaml_io.validate(vorlagen.read_workbook(_filled(tmp_path, [ORDENTLICH])))

        assert len(entries) == 1
        assert entries[0].ausgangsfrage == ORDENTLICH["Ausgangsfrage"]
        assert entries[0].referenz_korrekt_az == "WD 3 - 3000 - 029/23"
        assert entries[0].kategorie == Kategorie.GO

    def test_the_blank_rows_below_are_not_cases(self, tmp_path):
        """A sheet is handed out with room for 300 and comes back with eleven
        filled in. Treating the rest as errors would make it unusable."""
        entries = yaml_io.validate(vorlagen.read_workbook(_filled(tmp_path, [ORDENTLICH])))

        assert len(entries) == 1

    def test_a_grenzfall_needs_no_correct_source(self, tmp_path):
        """The rule the case store enforces at approval — a question the corpus
        does not cover has no correct source to name."""
        entries = yaml_io.validate(vorlagen.read_workbook(_filled(tmp_path, [GRENZFALL])))

        assert entries[0].grenzfall is True
        assert entries[0].referenz_korrekt == ""

    def test_nothing_arrives_approved(self, tmp_path):
        """Approval is a review decision. A sheet that could approve its own
        cases would make the review optional."""
        entries = yaml_io.validate(vorlagen.read_workbook(_filled(tmp_path, [ORDENTLICH])))

        assert entries[0].status == "entwurf"

    def test_no_test_id_comes_from_the_sheet(self, tmp_path):
        """Written by hand is how a number gets used twice, and the Vorlage is
        explicit that they are never reused."""
        entries = yaml_io.validate(vorlagen.read_workbook(_filled(tmp_path, [ORDENTLICH])))

        assert entries[0].test_id is None

    def test_a_missing_expected_answer_names_the_row(self, tmp_path):
        path = _filled(tmp_path, [{**ORDENTLICH, "Erwartete Antwort": None}])

        with pytest.raises(vorlagen.VorlageError, match="Zeile 2"):
            vorlagen.read_workbook(path)

    def test_an_ordinary_case_without_a_source_is_refused_while_the_sheet_is_open(self, tmp_path):
        """Caught here rather than at approval, which is weeks later and in
        front of somebody who did not write the case."""
        path = _filled(tmp_path, [{**ORDENTLICH, "Korrekte Quelle": None}])

        with pytest.raises(vorlagen.VorlageError, match="Grenzfall"):
            vorlagen.read_workbook(path)

    def test_an_unknown_category_says_which_are_allowed(self, tmp_path):
        path = _filled(tmp_path, [{**ORDENTLICH, "Kategorie": "XX"}])

        with pytest.raises(vorlagen.VorlageError, match="GO"):
            vorlagen.read_workbook(path)

    def test_columns_are_matched_by_header_not_position(self, tmp_path):
        """People add a working column, or reorder. Neither should break the
        import, and neither should silently shift every value by one."""
        path = _filled(tmp_path, [ORDENTLICH])
        book = openpyxl.load_workbook(path)
        sheet = book["Testfälle"]
        sheet.insert_cols(1)
        sheet.cell(row=1, column=1, value="Interne Notiz")
        sheet.cell(row=2, column=1, value="später prüfen")
        book.save(path)

        entries = yaml_io.validate(vorlagen.read_workbook(path))

        assert entries[0].ausgangsfrage == ORDENTLICH["Ausgangsfrage"]

    def test_a_removed_required_column_is_an_error_rather_than_silence(self, tmp_path):
        path = _filled(tmp_path, [ORDENTLICH])
        book = openpyxl.load_workbook(path)
        sheet = book["Testfälle"]
        sheet.delete_cols(2)  # Ausgangsfrage
        book.save(path)

        with pytest.raises(vorlagen.VorlageError, match="Ausgangsfrage"):
            vorlagen.read_workbook(path)

    def test_ja_and_nein_are_read_generously(self, tmp_path):
        """People write X, x, Ja, JA. Refusing those would be refusing the
        sheet over its least important column."""
        for written in ("Ja", "JA", "x", "1"):
            path = _filled(tmp_path, [{**GRENZFALL, "Grenzfall?": written}])
            entries = yaml_io.validate(vorlagen.read_workbook(path))
            assert entries[0].grenzfall is True, written
