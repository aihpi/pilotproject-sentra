"""Shared fixtures for the Sentra test suite.

Two test tiers:
  - Unit tests (no markers): run offline, no Qdrant/AI Hub needed.
  - Integration tests (@pytest.mark.integration): need Qdrant + AI Hub + ingested data.

Run everything:       uv run pytest
Unit only:            uv run pytest -m "not integration"
Integration only:     uv run pytest -m integration
"""

import os
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from sentra.config import Settings
from sentra.rag.embeddings import EmbeddingClient
from sentra.rag.generator import AnswerGenerator
from sentra.rag.store import VectorStore

# ── Credentials the offline tier does not have and does not need ────

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"

# A host that cannot resolve, per RFC 2606's reserved .invalid TLD. If an
# offline test ever does reach for the hub, it fails on DNS rather than quietly
# finding something real. A placeholder that worked would be worse than the bug
# this replaces.
PLACEHOLDER_HUB = "http://ai-hub.invalid/v1"
PLACEHOLDER_KEY = "offline-tests-do-not-call-the-hub"


def _placeholder_credentials_if_absent(env_file: Path) -> None:
    """Let Settings build when there is no .env and no credentials around.

    ai_hub_base_url and ai_hub_api_key are required with no defaults, and that
    is deliberate: a server booting against a placeholder hub and failing on
    the first search is worse than one refusing to start. The offline tier
    inherited the requirement without needing it — none of those tests calls
    the hub, they want a Settings for its collection names and paths — so CI,
    which has no .env and no secrets, could not run the suite at all.

    Set in the environment rather than passed to the settings fixture, because
    not every Settings() in the suite comes from that fixture: store_with in
    test_incremental_skip.py builds its own. They all read this.

    Nothing is set when an env file exists. Environment variables outrank the
    dotenv file in pydantic-settings, so doing it unconditionally would replace
    a developer's real credentials with a hub that cannot be reached, and take
    the integration tier down with it.
    """
    if env_file.is_file():
        return
    os.environ.setdefault("AI_HUB_BASE_URL", PLACEHOLDER_HUB)
    os.environ.setdefault("AI_HUB_API_KEY", PLACEHOLDER_KEY)


_placeholder_credentials_if_absent(ENV_FILE)


# ── Constants ───────────────────────────────────────────────────────

# The fixture corpus, versioned alongside the tests. Deliberately not data/:
# that holds whatever corpus the operator has ingested, which is thousands of
# documents, and a module-scoped fixture parsing all of them through Docling
# would take over an hour and exhaust memory. These 17 are a fixed set chosen to
# cover every Fachbereich, one English document and both joint-Aktenzeichen
# filenames.
DATA_DIR = Path(__file__).resolve().parent / "fixtures" / "corpus"

# The integration tier indexes the fixture corpus into collections of its own.
# It must not read whatever the operator has ingested: assertions like "these two
# documents are mutual top-10 neighbours" or "this Fachbereich is in the top 5"
# are only meaningful against a known, bounded index. Against an operational
# corpus of thousands they fail without anything being wrong.
TEST_COLLECTION = "sentra_test_chunks"
TEST_DOC_COLLECTION = "sentra_test_docs"

# Ground-truth metadata for the 17 fixture PDFs.
# Keyed by filename → expected fields (from manual inspection of the PDFs).
# Fields left as None mean "don't assert exact value, but check it's non-empty".
GROUND_TRUTH: dict[str, dict] = {
    "WD 3-029-23.pdf": {
        "aktenzeichen": "WD 3 - 3000 - 029/23",
        "fachbereich_number": "WD 3",
        "document_type_in": [
            "Ausarbeitung",
            "Sachstand",
            "Kurzinformation",
            "Dokumentation",
            "Sonstiges",
        ],
        "language": "de",
        "year_hint": 2023,
    },
    "EU 6-012-25.pdf": {
        "aktenzeichen": "EU 6 - 3000 - 012/25",
        "fachbereich_number": "EU 6",
        "document_type_in": [
            "Ausarbeitung",
            "Sachstand",
            "Kurzinformation",
            "Dokumentation",
            "Sonstiges",
        ],
        "language": "de",
        "year_hint": 2025,
    },
    "WD 10-013-23.pdf": {
        "aktenzeichen": "WD 10 - 3000 - 013/23",
        "fachbereich_number": "WD 10",
        "language": "de",
        "year_hint": 2023,
    },
    "WD 9-068-23.pdf": {
        "aktenzeichen": "WD 9 - 3000 - 068/23",
        "fachbereich_number": "WD 9",
        "language": "de",
        "year_hint": 2023,
    },
    "WD 6-052-24.pdf": {
        "aktenzeichen": "WD 6 - 3000 - 052/24",
        "fachbereich_number": "WD 6",
        "language": "de",
        "year_hint": 2024,
    },
    "WD 7-051-24.pdf": {
        "aktenzeichen": "WD 7 - 3000 - 051/24",
        "fachbereich_number": "WD 7",
        "language": "de",
        "year_hint": 2024,
    },
    "WD 10-042-22.pdf": {
        "aktenzeichen": "WD 10 - 3000 - 042/22",
        "fachbereich_number": "WD 10",
        "language": "de",
        "year_hint": 2022,
    },
    "WD 2-029-25.pdf": {
        "aktenzeichen": "WD 2 - 3000 - 029/25",
        "fachbereich_number": "WD 2",
        "language": "de",
        "year_hint": 2025,
    },
    "WD 1-019-24; WD 7-060-24.pdf": {
        # Joint document — first AZ should be extracted
        "aktenzeichen_startswith": "WD",
        "fachbereich_number_in": ["WD 1", "WD 7"],
        "language": "de",
        "year_hint": 2024,
    },
    "WD 7-085-22; WD 5-124-22.pdf": {
        "aktenzeichen_startswith": "WD",
        "fachbereich_number_in": ["WD 7", "WD 5"],
        "language": "de",
        "year_hint": 2022,
    },
    "WD 5-009-25.pdf": {
        "aktenzeichen": "WD 5 - 3000 - 009/25",
        "fachbereich_number": "WD 5",
        "language": "de",
        "year_hint": 2025,
    },
    "WD 4-086-24.pdf": {
        "aktenzeichen": "WD 4 - 3000 - 086/24",
        "fachbereich_number": "WD 4",
        "language": "de",
        "year_hint": 2024,
    },
    "WD 8-013-22.pdf": {
        "aktenzeichen": "WD 8 - 3000 - 013/22",
        "fachbereich_number": "WD 8",
        "language": "de",
        "year_hint": 2022,
    },
    "WD 6-094-23.pdf": {
        "aktenzeichen": "WD 6 - 3000 - 094/23",
        "fachbereich_number": "WD 6",
        "language": "de",
        "year_hint": 2023,
    },
    "WD 9-100-21.pdf": {
        "aktenzeichen": "WD 9 - 3000 - 100/21",
        "fachbereich_number": "WD 9",
        "language": "de",
        "year_hint": 2021,
    },
    "WD 2-027-25_EN.pdf": {
        "aktenzeichen": "WD 2 - 3000 - 027/25",
        "fachbereich_number": "WD 2",
        "language": "en",
        "year_hint": 2025,
    },
    "WD 8-011-22.pdf": {
        "aktenzeichen": "WD 8 - 3000 - 011/22",
        "fachbereich_number": "WD 8",
        "language": "de",
        "year_hint": 2022,
    },
}

VALID_DOCUMENT_TYPES = {
    "Ausarbeitung",
    "Sachstand",
    "Kurzinformation",
    "Dokumentation",
    "Sonstiges",
}
VALID_FACHBEREICH_NUMBERS = {
    "WD 1",
    "WD 2",
    "WD 3",
    "WD 4",
    "WD 5",
    "WD 6",
    "WD 7",
    "WD 8",
    "WD 9",
    "WD 10",
    "EU 6",
}

TOTAL_PDFS = len(GROUND_TRUTH)  # 17


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Backend settings, redirected at the test collections and fixture corpus.

    Credentials and the Qdrant URL come from the real .env where there is one,
    and from the placeholders above where there is not; everything that says
    *which data* comes from here, so a test run can never touch the operator's
    index or read their corpus.

    Auth is pinned off for the same reason. A developer who has configured a
    login locally would otherwise watch nine endpoint tests fail for a reason
    that has nothing to do with what they test — the guards refuse, correctly,
    and those tests were written before guards existed. Tests that are *about*
    auth build their own Settings and are unaffected.
    """
    if ENV_FILE.is_file():
        os.environ.setdefault("ENV_FILE", str(ENV_FILE))
    return Settings(
        _env_file=str(ENV_FILE),
        collection_name=TEST_COLLECTION,
        doc_collection_name=TEST_DOC_COLLECTION,
        documents_dir=str(DATA_DIR),
        admin_token="",
        sentra_users="",
        session_secret="",
    )


@pytest.fixture(scope="session")
def qdrant_available(settings: Settings) -> bool:
    """Whether the test index exists and holds something."""
    try:
        client = QdrantClient(url=settings.qdrant_url, timeout=5)
        names = {c.name for c in client.get_collections().collections}
        if settings.collection_name not in names:
            return False
        return client.count(settings.collection_name).count > 0
    except Exception:
        return False


def _skip_without_qdrant(qdrant_available: bool):
    if not qdrant_available:
        pytest.skip(
            f"Test index '{TEST_COLLECTION}' is missing or empty. Build it once with:\n"
            f"    uv run python -m tests.prepare_index\n"
            f"It indexes the {TOTAL_PDFS} fixture documents and leaves the "
            f"operator's collections untouched."
        )


@pytest.fixture()
def require_qdrant(qdrant_available: bool):
    """Skip the test if Qdrant is not available."""
    _skip_without_qdrant(qdrant_available)


# ── Markers ─────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def store(settings: Settings) -> VectorStore:
    """Shared VectorStore instance for integration tests."""
    return VectorStore(settings)


@pytest.fixture(scope="session")
def embedder(settings: Settings) -> EmbeddingClient:
    """Shared EmbeddingClient instance for integration tests."""
    return EmbeddingClient(settings)


@pytest.fixture(scope="session")
def generator(settings: Settings) -> AnswerGenerator:
    """Shared AnswerGenerator instance for integration tests."""
    return AnswerGenerator(settings)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: requires Qdrant + AI Hub (skip with -m 'not integration')"
    )
