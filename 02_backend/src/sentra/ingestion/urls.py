"""Extract external URLs from Bundestag document Markdown."""

import re
from dataclasses import dataclass

# Markdown link: [label](url)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")

# Bare URL (not inside a markdown link).
# Matches https:// followed by non-whitespace characters greedily.
# _clean_url() strips any trailing punctuation (.,;:) afterwards.
# NOTE: The previous regex used a lazy \S+? with "." in the lookahead,
# which truncated URLs at the first dot (e.g. https://www.example.com → https://www).
_BARE_URL_RE = re.compile(r"(?<!\()(https?://[^\s)\]>]+)")

# Domains to exclude (internal / navigation links)
_EXCLUDE_DOMAINS = {
    "www.bundestag.de",
    "bundestag.de",
    "dserver.bundestag.de",
    "dip.bundestag.de",
}


@dataclass
class ExtractedUrl:
    """A URL extracted from a document with context."""

    url: str
    label: str
    context: str


def _rejoin_broken_urls(text: str) -> str:
    """Rejoin URLs that Docling split across lines or with spaces.

    PDF-to-markdown conversion often breaks long URLs like::

        https://www.example.de/some-path/pa-
        ge/details.html

    or within a single line with a space::

        https://www.example.de/some-path/pa- ge/details.html

    **Hyphen handling** uses a domain-vs-path heuristic:

    - *Domain break* (no ``/`` after ``://``): the hyphen is always a PDF
      soft-hyphen artifact → **remove** it.
      Example: ``https://climate.ec.eu-\\nropa.eu`` → ``europa.eu``
    - *Path break* (URL already has a ``/`` path): the hyphen is likely a
      real slug separator → **keep** it.
      Example: ``https://example.de/pdf-\\nfiles/`` → ``pdf-files/``

    Loops because a single URL may be split across 3+ lines.
    """

    def _rejoin(match: re.Match) -> str:
        prefix = match.group(1)
        continuation = match.group(2)
        # Everything after :// — if it contains a / the break is in the path
        after_scheme = prefix.split("://", 1)[-1]
        if "/" not in after_scheme:
            # Domain break: hyphen is always a PDF artifact
            return prefix + continuation
        # Path break: keep the hyphen (URL slugs use real hyphens)
        return prefix + "-" + continuation

    # Pattern 1: hyphen + newline (URL broken across lines)
    nl_pattern = re.compile(r"(https?://\S+)-\s*\n\s*(\S)")
    prev = None
    while prev != text:
        prev = text
        text = nl_pattern.sub(_rejoin, text)

    # Pattern 2: hyphen + space(s) on the same line (no newline)
    # Continuation must start with [a-z0-9] to avoid joining with sentence text.
    sp_pattern = re.compile(r"(https?://\S+)-[ \t]+([a-z0-9])")
    prev = None
    while prev != text:
        prev = text
        text = sp_pattern.sub(_rejoin, text)

    return text


def extract_urls(markdown: str) -> list[ExtractedUrl]:
    """Extract external URLs from a Markdown document.

    Returns deduplicated URLs with labels and surrounding context.
    """
    seen: set[str] = set()
    results: list[ExtractedUrl] = []

    # Pre-process: rejoin URLs broken across lines by Docling
    markdown = _rejoin_broken_urls(markdown)

    # 1. Markdown links [label](url)
    for match in _MD_LINK_RE.finditer(markdown):
        label = match.group(1).strip()
        url = _clean_url(match.group(2))
        if not url or url in seen or not _has_valid_domain(url) or _is_excluded(url):
            continue
        seen.add(url)
        context = _extract_context(markdown, match.start(), match.end())
        results.append(ExtractedUrl(url=url, label=label, context=context))

    # 2. Bare URLs not already captured
    for match in _BARE_URL_RE.finditer(markdown):
        url = _clean_url(match.group(0))
        if not url or url in seen or not _has_valid_domain(url) or _is_excluded(url):
            continue
        seen.add(url)
        context = _extract_context(markdown, match.start(), match.end())
        results.append(ExtractedUrl(url=url, label="", context=context))

    return results


def _clean_url(url: str) -> str:
    """Strip trailing punctuation and normalize.

    Removes Docling markdown escape artifacts (backslash before underscores)
    and HTML entity leaks (&amp;).
    """
    # Remove Docling's backslash-escaped underscores: \_  →  _
    url = url.replace(r"\_", "_")
    # Remove &amp; HTML entities (Docling sometimes leaks these)
    url = url.replace("&amp;", "&")
    # Strip trailing punctuation that is not part of the URL
    url = url.rstrip(".,;:)")
    return url


def _has_valid_domain(url: str) -> bool:
    """Check if a URL has a syntactically valid domain (at least one dot).

    Rejects fragments from PDF line-break hyphenation like 'https://rund-'
    where Docling broke a URL across lines.
    """
    match = re.match(r"https?://([^/:]+)", url)
    if not match:
        return False
    domain = match.group(1)
    return "." in domain


def _is_excluded(url: str) -> bool:
    """Check if a URL belongs to an excluded domain."""
    # Extract domain from URL
    match = re.match(r"https?://([^/:]+)", url)
    if not match:
        return True
    domain = match.group(1).lower()
    return domain in _EXCLUDE_DOMAINS


def _extract_context(text: str, start: int, end: int) -> str:
    """Extract a short context window around the URL occurrence."""
    # Find the enclosing line(s)
    line_start = text.rfind("\n", 0, start)
    line_start = 0 if line_start == -1 else line_start + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end

    context = text[line_start:line_end].strip()
    # Strip markdown formatting for readability
    context = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", context)
    context = context.lstrip("#- ").strip()

    # Truncate if too long
    if len(context) > 200:
        context = context[:200].rstrip() + "..."
    return context
