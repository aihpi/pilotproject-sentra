"""Answer generation (UC#10 + UC#2) tests against real indexed data.

These tests verify that the LLM produces grounded answers: non-empty,
citing real documents, and responding to impossible filters gracefully.

Important: These tests call the real LLM (AI Hub). Each test involves
one LLM call (~2-5 seconds). Keep the test count small and focused.

Requires: Qdrant + AI Hub running + data ingested (mark: integration).
Run:  uv run pytest tests/test_answer_generation.py -v -m integration
"""

import re

import pytest

from sentra.services.explorer import answer_question, generate_overview

pytestmark = pytest.mark.integration


# Known Aktenzeichen from our 17-doc dataset (for validating source refs)
KNOWN_AZ_PATTERN = re.compile(r"^(WD|EU)\s+\d+\s+-\s+3000\s+-\s+\d+/\d+$")


# ── UC#10: Fachfrage (focused answer) ──────────────────────────────


class TestFachfrageAnswer:
    def test_returns_nonempty_answer(self, require_qdrant, settings):
        result = answer_question(
            query="Welche Regelungen gibt es zur Gesundheitsversorgung?",
            date_from=None, date_to=None,
            top_k=5, settings=settings,
        )
        assert len(result.text) > 50, (
            f"Answer too short ({len(result.text)} chars): '{result.text[:100]}'"
        )

    def test_cites_sources(self, require_qdrant, settings):
        result = answer_question(
            query="Welche Regelungen gibt es zum Umweltschutz?",
            date_from=None, date_to=None,
            top_k=5, settings=settings,
        )
        assert len(result.sources) >= 1, "Answer has zero source references"

    def test_sources_are_real_documents(self, require_qdrant, settings):
        """Every cited source must have a valid Aktenzeichen (not hallucinated)."""
        result = answer_question(
            query="Was sagt das Grundgesetz zur Verfassung?",
            date_from=None, date_to=None,
            top_k=5, settings=settings,
        )
        for src in result.sources:
            assert KNOWN_AZ_PATTERN.match(src.aktenzeichen), (
                f"Source has invalid AZ pattern: '{src.aktenzeichen}'"
            )
            assert src.title, f"Source {src.aktenzeichen} has empty title"
            assert src.fachbereich, f"Source {src.aktenzeichen} has empty fachbereich"
            assert src.source_file, f"Source {src.aktenzeichen} has empty source_file"

    def test_default_system_prompt_used(self, require_qdrant, settings):
        """When no custom prompt is passed, the FACHFRAGE_PROMPT should be echoed back."""
        result = answer_question(
            query="Was ist Sozialversicherung?",
            date_from=None, date_to=None,
            top_k=5, settings=settings,
        )
        assert result.system_prompt is not None
        assert "Fachfrage" in result.system_prompt or "präzise" in result.system_prompt

    def test_custom_system_prompt_echoed(self, require_qdrant, settings):
        custom = "Antworte nur in Stichpunkten."
        result = answer_question(
            query="Was ist Arbeitsrecht?",
            date_from=None, date_to=None,
            top_k=5, settings=settings,
            system_prompt=custom,
        )
        assert result.system_prompt == custom

    def test_impossible_filter_returns_no_documents_message(self, require_qdrant, settings):
        """When filters exclude all documents, we get a graceful message, not a crash."""
        result = answer_question(
            query="Was ist Datenschutz?",
            date_from="2000", date_to="2000",  # no docs from year 2000
            top_k=5, settings=settings,
        )
        assert len(result.sources) == 0
        # Should contain a "no documents found" message
        assert "keine" in result.text.lower() or "nicht" in result.text.lower() or len(result.text) < 200

    def test_filters_restrict_sources(self, require_qdrant, settings):
        """When filtering by WD 9, all source references should be from WD 9."""
        result = answer_question(
            query="Gesundheitspolitik Krankenversicherung",
            date_from=None, date_to=None,
            top_k=5, settings=settings,
            fachbereich="WD 9",
        )
        for src in result.sources:
            fb_prefix = src.aktenzeichen.split(" - ")[0].strip()
            assert fb_prefix == "WD 9", (
                f"Filtered for WD 9 but source is from {src.aktenzeichen}"
            )


# ── UC#2: Themenüberblick (structured overview) ───────────────────


class TestOverview:
    def test_returns_nonempty_overview(self, require_qdrant, settings):
        result = generate_overview(
            query="Umweltrecht und Klimaschutz in Deutschland",
            date_from=None, date_to=None,
            top_k=5, settings=settings,
        )
        assert len(result.text) > 100, (
            f"Overview too short ({len(result.text)} chars)"
        )

    def test_overview_has_markdown_structure(self, require_qdrant, settings):
        """Overview should contain markdown headings (##) per the OVERVIEW_PROMPT."""
        result = generate_overview(
            query="Arbeitsrecht und Sozialversicherung",
            date_from=None, date_to=None,
            top_k=5, settings=settings,
        )
        assert "##" in result.text, (
            "Overview lacks markdown headings — should be structured per OVERVIEW_PROMPT"
        )

    def test_overview_cites_sources(self, require_qdrant, settings):
        result = generate_overview(
            query="Gesetzgebung und parlamentarische Praxis",
            date_from=None, date_to=None,
            top_k=5, settings=settings,
        )
        assert len(result.sources) >= 1, "Overview has zero sources"

    def test_overview_default_prompt(self, require_qdrant, settings):
        result = generate_overview(
            query="Europäische Integration",
            date_from=None, date_to=None,
            top_k=5, settings=settings,
        )
        assert result.system_prompt is not None
        assert "Überblick" in result.system_prompt or "thematisch" in result.system_prompt
