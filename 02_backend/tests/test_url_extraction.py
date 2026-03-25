"""Unit tests for URL extraction from Docling markdown.

These run offline — no Qdrant or AI Hub required.
Run:  uv run pytest tests/test_url_extraction.py -v
"""

from sentra.ingestion.urls import _rejoin_broken_urls, extract_urls


# ── _rejoin_broken_urls ─────────────────────────────────────────────


class TestRejoinNewlineBreaks:
    """URLs broken across lines with hyphen + newline."""

    def test_simple_newline_break(self):
        text = "See https://example.de/pa-\nge for details."
        result = _rejoin_broken_urls(text)
        # Path break → keep hyphen
        assert "https://example.de/pa-ge" in result

    def test_newline_break_with_leading_whitespace(self):
        text = "https://example.de/pa-\n  ge/details"
        result = _rejoin_broken_urls(text)
        assert "https://example.de/pa-ge/details" in result

    def test_multi_line_break(self):
        """URL broken across 3 lines."""
        text = "https://example.de/very-\nlong-\npath/file.html"
        result = _rejoin_broken_urls(text)
        assert "https://example.de/very-long-path/file.html" in result

    def test_domain_break_newline(self):
        """Break in the domain: hyphen must be removed."""
        text = "https://climate.ec.eu-\nropa.eu/some-path"
        result = _rejoin_broken_urls(text)
        assert "https://climate.ec.europa.eu/some-path" in result

    def test_path_break_keeps_hyphen(self):
        """Break in a slug-style path: hyphen must be kept."""
        text = "https://example.de/pdf-\nfiles/a-p-b/doc.pdf"
        result = _rejoin_broken_urls(text)
        assert "https://example.de/pdf-files/a-p-b/doc.pdf" in result

    def test_path_break_slug_continuation(self):
        """preise-bis should remain preise-bis, not preisebis."""
        text = "https://www.ey.com/path/preise-\nbis-2030"
        result = _rejoin_broken_urls(text)
        assert "preise-bis-2030" in result


class TestRejoinSpaceBreaks:
    """URLs broken with hyphen + space (no newline) — Docling same-line artifact."""

    def test_simple_space_break(self):
        text = "https://www.umweltbundesamt.de/da- ten/klima/foo"
        result = _rejoin_broken_urls(text)
        # Path break → keep hyphen
        assert "https://www.umweltbundesamt.de/da-ten/klima/foo" in result

    def test_domain_space_break(self):
        """Domain broken with space: hyphen must be removed."""
        text = "https://climate.ec.eu- ropa.eu/eu-action/foo"
        result = _rejoin_broken_urls(text)
        assert "https://climate.ec.europa.eu/eu-action/foo" in result

    def test_space_break_followed_by_semicolon(self):
        """URL broken with space, continuation ends with semicolon-separated next URL."""
        text = (
            "https://www.dehst.de/path/klima- "
            r"schutzambition\_node.html; https://other.de/"
        )
        result = _rejoin_broken_urls(text)
        assert "klima-schutzambition" in result
        assert "https://other.de/" in result

    def test_space_break_slug_path(self):
        """Break in a multi-word slug — hyphen is kept."""
        text = "https://www.dihk.de/themen/ausgaben-2024- deutlich-102776."
        result = _rejoin_broken_urls(text)
        assert "ausgaben-2024-deutlich-102776" in result

    def test_no_false_positive_with_sentence(self):
        """Should NOT rejoin when followed by an uppercase letter (sentence start)."""
        text = "https://example.de/api- See the docs."
        result = _rejoin_broken_urls(text)
        # "See" starts with uppercase → no match
        assert "https://example.de/api-" in result

    def test_multiple_space_breaks(self):
        """URL with multiple space breaks is rejoined iteratively."""
        text = "https://example.de/a- b- c/file.html"
        result = _rejoin_broken_urls(text)
        assert "a-b-c/file.html" in result


class TestRejoinRealWorldCases:
    """Test cases derived from actual broken URLs in Bundestag documents."""

    def test_dehst_klimaschutzambition(self):
        text = (
            "https://www.dehst.de/DE/Europaeischer-Emissionshandel/"
            r"Reform-Perspektiven/Klimaschutzambitionen/klima- schutzambition\_node.html"
        )
        result = _rejoin_broken_urls(text)
        assert "klima-schutzambition" in result
        assert "klima- " not in result

    def test_umweltbundesamt_daten(self):
        text = (
            "https://www.umweltbundesamt.de/da- "
            "ten/klima/der-europaeische-emissionshandel"
        )
        result = _rejoin_broken_urls(text)
        assert "da-ten/klima" in result
        assert "da- " not in result

    def test_climate_ec_europa_domain(self):
        text = (
            "https://climate.ec.eu- "
            r"ropa.eu/eu-action/eu-emissions-trading-system-eu-ets/social-climate-fund\_en"
        )
        result = _rejoin_broken_urls(text)
        assert "europa.eu" in result
        assert "eu-ropa" not in result

    def test_statista_pro_jahr(self):
        text = (
            "https://de.statista.com/statistik/daten/studie/1357535/"
            "umfrage/auktionserloese-aus-emissionszertifikaten-pro- jahr."
        )
        result = _rejoin_broken_urls(text)
        assert "pro-jahr" in result

    def test_agora_package_based(self):
        text = (
            "https://www.agora-energiewende.de/en/publications/"
            "a-fit-for-55-package- based-on-environmental-integrity"
        )
        result = _rejoin_broken_urls(text)
        assert "package-based-on" in result

    def test_vbw_freizugaengliche(self):
        text = (
            "https://www.vbw-bayern.de/Redaktion/Frei- "
            "zugaengliche-Medien/Abteilungen-GS"
        )
        result = _rejoin_broken_urls(text)
        assert "Frei-zugaengliche-Medien" in result


# ── extract_urls (end-to-end) ───────────────────────────────────────


class TestExtractUrls:
    def test_extracts_bare_url(self):
        md = "See https://example.de/page for details."
        urls = extract_urls(md)
        assert any(u.url == "https://example.de/page" for u in urls)

    def test_extracts_markdown_link(self):
        md = "See [Example](https://example.de/page) for details."
        urls = extract_urls(md)
        assert any(u.url == "https://example.de/page" for u in urls)
        assert any(u.label == "Example" for u in urls)

    def test_excludes_bundestag_domains(self):
        md = "https://www.bundestag.de/foo and https://dserver.bundestag.de/bar"
        urls = extract_urls(md)
        assert len(urls) == 0

    def test_cleans_backslash_underscores(self):
        md = r"https://example.de/some\_path/file\_name.html"
        urls = extract_urls(md)
        assert any(u.url == "https://example.de/some_path/file_name.html" for u in urls)

    def test_cleans_html_entities(self):
        md = "https://example.de/page?a=1&amp;b=2"
        urls = extract_urls(md)
        assert any(u.url == "https://example.de/page?a=1&b=2" for u in urls)

    def test_strips_trailing_punctuation(self):
        md = "See https://example.de/page."
        urls = extract_urls(md)
        assert any(u.url == "https://example.de/page" for u in urls)

    def test_space_broken_url_is_complete(self):
        """A URL broken with hyphen+space should be extracted as a complete URL."""
        md = (
            "Footnote: https://www.umweltbundesamt.de/da- "
            "ten/klima/der-europaeische-emissionshandel#anchor"
        )
        urls = extract_urls(md)
        assert len(urls) == 1
        url = urls[0].url
        assert "da-ten/klima" in url
        assert url.endswith("#anchor")

    def test_domain_broken_url_has_valid_domain(self):
        md = (
            "https://climate.ec.eu- "
            r"ropa.eu/eu-action/social-climate-fund\_en?prefLang=de"
        )
        urls = extract_urls(md)
        assert len(urls) == 1
        assert "europa.eu" in urls[0].url

    def test_deduplicates_urls(self):
        md = (
            "First: https://example.de/page\n"
            "Second: https://example.de/page\n"
        )
        urls = extract_urls(md)
        assert len(urls) == 1

    def test_rejects_domain_fragments(self):
        """URLs with no valid domain (no dot) should be filtered out."""
        md = "https://rund- some text here"
        urls = extract_urls(md)
        # After rejoin: "https://rund-" or "https://rundsome" — no dot in domain
        assert len(urls) == 0
