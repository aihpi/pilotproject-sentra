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

# ── Constants ───────────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parents[2] / "03_data" / "Ausarbeitungen"

# Ground-truth metadata for the 17 test PDFs.
# Keyed by filename → expected fields (from manual inspection of the PDFs).
# Fields left as None mean "don't assert exact value, but check it's non-empty".
GROUND_TRUTH: dict[str, dict] = {
    "WD 3-029-23.pdf": {
        "aktenzeichen": "WD 3 - 3000 - 029/23",
        "fachbereich_number": "WD 3",
        "document_type_in": ["Ausarbeitung", "Sachstand", "Kurzinformation", "Dokumentation", "Sonstiges"],
        "language": "de",
        "year_hint": 2023,
    },
    "EU 6-012-25.pdf": {
        "aktenzeichen": "EU 6 - 3000 - 012/25",
        "fachbereich_number": "EU 6",
        "document_type_in": ["Ausarbeitung", "Sachstand", "Kurzinformation", "Dokumentation", "Sonstiges"],
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

VALID_DOCUMENT_TYPES = {"Ausarbeitung", "Sachstand", "Kurzinformation", "Dokumentation", "Sonstiges"}
VALID_FACHBEREICH_NUMBERS = {
    "WD 1", "WD 2", "WD 3", "WD 4", "WD 5",
    "WD 6", "WD 7", "WD 8", "WD 9", "WD 10", "EU 6",
}

TOTAL_PDFS = len(GROUND_TRUTH)  # 17


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Load settings from the backend .env file."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.is_file():
        os.environ.setdefault("ENV_FILE", str(env_path))
    return Settings(_env_file=str(env_path))


@pytest.fixture(scope="session")
def qdrant_available(settings: Settings) -> bool:
    """Check whether Qdrant is reachable and contains data."""
    try:
        client = QdrantClient(url=settings.qdrant_url, timeout=5)
        collections = client.get_collections().collections
        names = {c.name for c in collections}
        return settings.collection_name in names
    except Exception:
        return False


def _skip_without_qdrant(qdrant_available: bool):
    if not qdrant_available:
        pytest.skip("Qdrant not reachable or collection not indexed — skipping integration test")


@pytest.fixture()
def require_qdrant(qdrant_available: bool):
    """Skip the test if Qdrant is not available."""
    _skip_without_qdrant(qdrant_available)


# ── Markers ─────────────────────────────────────────────────────────


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires Qdrant + AI Hub (skip with -m 'not integration')")
