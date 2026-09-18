"""Uploading a filled collection sheet, over HTTP.

The boundary this endpoint has to hold is narrower than the CLI's, and is the
whole reason a browser may post here at all: **a sheet can only ever create
drafts.** The reader forces `status: entwurf` whatever the file says, so an
upload cannot approve anything and therefore cannot change what a round
measures against. YAML import, which can approve, stays with the CLI — there
the pull request is the review.

Most of what could go wrong here is somebody sending the wrong file, so that is
most of what is tested. The reader's own rules are covered in test_vorlagen.py;
what matters at this level is that its message survives the trip.
"""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from sentra_eval.app import create_app
from sentra_eval.config import get_eval_settings
from sentra_eval.db import Base, get_engine

openpyxl = pytest.importorskip("openpyxl", reason="needs `uv sync --extra vorlagen`")

from sentra_eval import vorlagen  # noqa: E402  - after the skip


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("JUDGE_BASE_URL", "http://judge.invalid/v1")
    monkeypatch.setenv("JUDGE_API_KEY", "not-a-real-key")
    monkeypatch.setenv("JUDGE_MODEL", "a-judge-that-is-not-the-chat-model")
    monkeypatch.setenv("CHAT_MODEL_UNDER_TEST", "llama-3-3-70b")
    monkeypatch.setenv("EVAL_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'eval.db'}")
    get_eval_settings.cache_clear()
    get_engine.cache_clear()
    Base.metadata.create_all(get_engine())

    with TestClient(create_app()) as client:
        yield client

    get_eval_settings.cache_clear()
    get_engine.cache_clear()


ORDENTLICH = {
    "Kategorie": "GO",
    "Ausgangsfrage": "Wie lange darf ein Redner im Plenum sprechen?",
    "Erwartete Antwort": "15 Minuten je Fraktion nach § 35 GOBT.",
    "Korrekte Quelle": "GOBT § 35",
    "Grenzfall?": "nein",
}


def _sheet(rows: list[dict]) -> bytes:
    """A real template, filled the way a person fills it: by column label."""
    book = vorlagen.build_workbook()
    sheet = book["Testfälle"]
    columns = {f.label: index for index, f in enumerate(vorlagen.FIELDS, start=1)}
    for offset, row in enumerate(rows, start=2):
        for label, value in row.items():
            sheet.cell(row=offset, column=columns[label], value=value)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _post(client: TestClient, payload: bytes):
    return client.post("/api/eval/faelle/import", content=payload)


class TestAGoodSheet:
    def test_the_rows_become_cases(self, client):
        response = _post(client, _sheet([ORDENTLICH]))

        assert response.status_code == 200
        assert len(response.json()["angelegt"]) == 1

    def test_it_reports_the_test_ids_rather_than_a_count(self, client):
        """ "3 angelegt" leaves the author wondering which three, and the
        Test-IDs are what they will look for next."""
        response = _post(client, _sheet([ORDENTLICH, {**ORDENTLICH, "Kategorie": "GV"}]))

        assert response.json()["angelegt"] == ["TF-GO-001", "TF-GV-001"]

    def test_nothing_uploaded_is_approved(self, client):
        """The boundary the whole endpoint rests on. An upload that could
        approve a case could change what a round measures against."""
        _post(client, _sheet([ORDENTLICH]))

        cases = client.get("/api/eval/cases").json()

        assert [v["status"] for c in cases for v in c["versions"]] == ["entwurf"]

    def test_uploading_the_same_sheet_twice_changes_nothing(self, client):
        """People re-send a corrected sheet with the rows they already sent.
        Each row carries no Test-ID, so this is worth being explicit about."""
        first = _post(client, _sheet([ORDENTLICH])).json()

        second = _post(client, _sheet([ORDENTLICH])).json()

        assert first["angelegt"] == ["TF-GO-001"]
        # Without a Test-ID the second upload is a new case, not the same one.
        # That is the documented behaviour of the file format and the reason
        # the response lists IDs: it is visible rather than silent.
        assert second["angelegt"] == ["TF-GO-002"]


class TestTheWrongFile:
    def test_something_that_is_not_a_workbook(self, client):
        response = _post(client, b"Das ist kein Excel, das ist Text.")

        assert response.status_code == 422
        assert "Vorlage" in response.json()["detail"]

    def test_an_empty_body(self, client):
        response = _post(client, b"")

        assert response.status_code == 400

    def test_something_far_too_large(self, client):
        """The sheet handed out weighs about 19 KB. Reading a very large body
        into memory to discover it is not a spreadsheet is how one request
        takes the harness down."""
        response = _post(client, b"x" * (6 * 1024 * 1024))

        assert response.status_code == 413


class TestABadRow:
    def test_the_row_number_survives_the_trip(self, client):
        """The reader numbers rows the way Excel does. That message is the only
        version of this error worth showing anybody, so it has to arrive
        intact rather than becoming "invalid input"."""
        response = _post(client, _sheet([{**ORDENTLICH, "Erwartete Antwort": None}]))

        assert response.status_code == 422
        assert "Zeile 2" in response.json()["detail"]

    def test_an_ordinary_case_with_no_source_says_what_to_do_instead(self, client):
        response = _post(client, _sheet([{**ORDENTLICH, "Korrekte Quelle": None}]))

        assert response.status_code == 422
        assert "Grenzfall" in response.json()["detail"]

    def test_a_bad_row_writes_nothing_at_all(self, client):
        """All or nothing. A sheet half-imported leaves somebody reconciling
        which rows landed, which is worse than importing none of them."""
        _post(client, _sheet([ORDENTLICH, {**ORDENTLICH, "Kategorie": "XX"}]))

        assert client.get("/api/eval/cases").json() == []
