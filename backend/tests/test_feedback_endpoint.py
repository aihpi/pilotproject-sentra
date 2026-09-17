"""Reading feedback back.

SENTRA has recorded ratings since #16 and nothing ever read them. The
evaluation harness needs them: Phase 1 of the Vorlage asks for known problem
cases from earlier feedback to be taken into a round on purpose, "da sich dort
erfahrungsgemäß Schwachstellen wiederholen" — and the harness is a separate
process with no access to that file.

Offline. The endpoint reads a file and needs neither Qdrant nor the AI Hub,
which is why these live here rather than in test_api_endpoints.py, whose whole
module is integration-marked.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentra.api.routes import router
from sentra.config import get_settings

ENTRIES = (
    {
        "timestamp": "2026-09-01T10:00:00+00:00",
        "question": "Redezeit?",
        "answer": "45 Minuten.",
        "rating": "negative",
        "comment": "Falsch.",
    },
    {
        "timestamp": "2026-09-02T10:00:00+00:00",
        "question": "Ältestenrat?",
        "answer": "Der Präsident.",
        "rating": "positive",
        "comment": None,
    },
)


def _client(settings, path):
    own = settings.model_copy(update={"feedback_file": str(path)})
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: own
    return TestClient(app)


@pytest.fixture
def written(tmp_path):
    path = tmp_path / "feedback.jsonl"
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in ENTRIES) + "\n",
        encoding="utf-8",
    )
    return path


class TestReadingFeedback:
    def test_entries_come_back_newest_first(self, settings, written):
        body = _client(settings, written).get("/api/feedback").json()

        assert [e["question"] for e in body] == ["Ältestenrat?", "Redezeit?"]

    def test_they_can_be_filtered_by_rating(self, settings, written):
        body = _client(settings, written).get("/api/feedback?rating=negative").json()

        assert [e["question"] for e in body] == ["Redezeit?"]

    def test_each_entry_has_a_stable_id(self, settings, written):
        """Derived from timestamp and question, because the file is append-only
        lines written since #16 with no identifier. Giving it one retroactively
        would mean rewriting a log in place."""
        client = _client(settings, written)

        first = client.get("/api/feedback").json()
        second = client.get("/api/feedback").json()

        assert [e["id"] for e in first] == [e["id"] for e in second]
        assert len({e["id"] for e in first}) == 2

    def test_a_malformed_line_does_not_hide_the_rest(self, settings, written):
        """The file is append-only and written by a different code path. One
        bad line should not make every earlier rating unreadable."""
        written.write_text(written.read_text(encoding="utf-8") + "{ not json\n", encoding="utf-8")

        assert len(_client(settings, written).get("/api/feedback").json()) == 2

    def test_no_file_yet_is_an_empty_list(self, settings, tmp_path):
        """Before anybody has rated anything. Not an error."""
        assert _client(settings, tmp_path / "nothing.jsonl").get("/api/feedback").json() == []

    def test_the_answer_is_served_too(self, settings, written):
        """The harness shows it to a reviewer drafting a case, so they can see
        what went wrong — while deliberately not storing it as the expected
        answer."""
        body = _client(settings, written).get("/api/feedback?rating=negative").json()

        assert body[0]["answer"] == "45 Minuten."
