"""Splitting a parsed document into chunks, and remembering where each came from.

This walked the Markdown export and split it on `#` headers. It walks the
document's blocks now, because a string cannot say where any of it came from
and technique 4.3a needs exactly that: whether the cited passage supports the
claim is answered by a person, and a person needs somewhere to look.

**The strategy is unchanged.** Split at section headings, keep short documents
whole, split an oversized section at paragraph boundaries. What changed is that
a heading is a `section_header` block rather than a `#` in a string, and a
paragraph boundary is the edge of a block rather than a blank line — which is
the same boundary, described by the parser instead of inferred from whitespace.

Chunk boundaries do move in a few cases, and that is the cost of the feature: a
table is one string in the export and several blocks here, and the old
boilerplate patterns matched text spanning several items. Every point in Qdrant
is stale as a result, which #134 already required.
"""

import logging
import re

from sentra.domain import Chunk, DocumentMetadata
from sentra.ingestion.parser import TextBlock

logger = logging.getLogger(__name__)

# Boilerplate, matched against a whole block rather than surgically against a
# string. Docling puts page headers and footers in the furniture layer, so most
# of what the old patterns existed for never reaches the body at all; what is
# left is whole blocks — the disclaimer, the standing note about Weitergabe —
# and dropping a block is a cleaner act than deleting a span.
_BOILERPLATE_PATTERNS = [
    re.compile(r"Die Wissenschaftlichen Dienste des Deutschen Bundestages unterstützen"),
    re.compile(r"Der Fachbereich berät über die dabei zu berücksichtigenden Fragen"),
    re.compile(r"©\s*\d{4}\s*Deutscher Bundestag"),
    re.compile(r"^Wissenschaftliche Dienste\s*$", re.MULTILINE),
    re.compile(r"^Deutscher Bundestag\s*$", re.MULTILINE),
    re.compile(r"^\s*\*\*\*\s*$"),
    re.compile(r"<!--\s*image\s*-->"),
]

# Headings that introduce no content worth retrieving.
_SKIPPED_HEADINGS = ("inhaltsverzeichnis", "aktenzeichen")

_SECTION_NUMBER_RE = re.compile(r"^([\d.]+\.?)\s")

# 1 token ≈ 4 characters of German.
_CHARS_PER_TOKEN = 4

# Below this a section is navigation or a stray line rather than content.
_MIN_SECTION_CHARS = 30

# Below this a document is one idea and splitting it only separates a question
# from its answer. A Kurzinformation is one by definition.
_SHORT_DOCUMENT_CHARS = 1000


def is_boilerplate(text: str) -> bool:
    """Whether a block is standing text rather than content.

    Applied **after** paragraph numbering and never before. A reviewer counting
    down page 2 counts the disclaimer along with everything else, because it is
    printed there; numbering only the survivors would produce citations that
    are internally consistent and do not match the paper in front of them. On
    WD 10-042-22.pdf the disclaimer is page 2, paragraph 2.
    """
    return any(pattern.search(text) for pattern in _BOILERPLATE_PATTERNS)


def chunk_document(
    blocks: list[TextBlock], metadata: DocumentMetadata, max_tokens: int = 2048
) -> list[Chunk]:
    """Split a parsed document into chunks that carry their provenance."""
    body = [block for block in blocks if block.text.strip() and not is_boilerplate(block.text)]
    if not body:
        return []

    if metadata.document_type == "Kurzinformation" or _length(body) < _SHORT_DOCUMENT_CHARS:
        whole = _as_chunk(body, title=metadata.title, path="", index=0, metadata=metadata)
        return [whole] if whole else []

    chunks: list[Chunk] = []
    for title, path, section in _sections(body):
        if _length(section) < _MIN_SECTION_CHARS:
            continue

        # A section that is only its own heading has nothing to answer from.
        # It happens wherever a numbered heading introduces sub-headings — "2.
        # Situation in einzelnen EU-Mitgliedstaaten" followed straight by
        # "2.1. Belgien" — and it was indexed before, because a heading long
        # enough cleared the character minimum. It would now also be cited, as
        # a passage at paragraph zero of its page, which is how a chunk with no
        # paragraph in it announces itself.
        if not any(block.paragraph is not None for block in section):
            continue

        if _length(section) // _CHARS_PER_TOKEN <= max_tokens:
            parts = [section]
        else:
            parts = _split_oversized(section, max_tokens)

        for part_index, part in enumerate(parts):
            heading = f"{title} (Teil {part_index + 1})" if len(parts) > 1 else title
            chunk = _as_chunk(part, title=heading, path=path, index=len(chunks), metadata=metadata)
            if chunk:
                chunks.append(chunk)

    for index, chunk in enumerate(chunks):
        chunk.chunk_index = index

    logger.info(
        "Chunked %s into %d chunks (source: %s)",
        metadata.aktenzeichen or metadata.title,
        len(chunks),
        metadata.source_file,
    )
    return chunks


def _sections(blocks: list[TextBlock]) -> list[tuple[str, str, list[TextBlock]]]:
    """Group blocks into sections at each heading.

    Anything before the first heading is an Einleitung, as it was — a paper
    whose first page is title and abstract should not lose them.
    """
    sections: list[tuple[str, str, list[TextBlock]]] = []
    title, path = "Einleitung", ""
    current: list[TextBlock] = []
    seen_heading = False

    for block in blocks:
        if block.label != "section_header":
            current.append(block)
            continue

        if current and (seen_heading or _length(current) > 50):
            sections.append((title, path, current))
        current = []

        heading = block.text.strip()
        lowered = heading.lower()
        if lowered in _SKIPPED_HEADINGS or lowered.startswith("aktenzeichen:"):
            # Skipped, and the blocks under it go with it: a table of contents
            # is navigation, and retrieving it answers nothing.
            title, path = "", ""
            seen_heading = True
            continue

        title = heading
        path = _section_number(heading)
        seen_heading = True
        # The heading belongs to its section's text, for context in the answer.
        current = [block]

    if current and title:
        sections.append((title, path, current))

    return [(title, path, blocks) for title, path, blocks in sections if title]


def _split_oversized(blocks: list[TextBlock], max_tokens: int) -> list[list[TextBlock]]:
    """Split a long section at block boundaries.

    A block boundary *is* a paragraph boundary — which the old version inferred
    from blank lines in a string, and the parser now simply knows.
    """
    parts: list[list[TextBlock]] = []
    current: list[TextBlock] = []
    budget = 0

    for block in blocks:
        cost = len(block.text) // _CHARS_PER_TOKEN
        if current and budget + cost > max_tokens:
            parts.append(current)
            current = [block]
            budget = cost
        else:
            current.append(block)
            budget += cost

    if current:
        parts.append(current)
    return parts


def _as_chunk(
    blocks: list[TextBlock], *, title: str, path: str, index: int, metadata: DocumentMetadata
) -> Chunk | None:
    text = "\n\n".join(block.text.strip() for block in blocks if block.text.strip())
    if not text:
        return None

    pages = [block.page for block in blocks]
    first, last = blocks[0], blocks[-1]

    return Chunk(
        text=text,
        section_title=title,
        section_path=path,
        chunk_index=index,
        metadata=metadata,
        page_from=min(pages),
        page_to=max(pages),
        # The paragraph numbers belong to the first and last page respectively,
        # because the count restarts on each page. A heading has no number of
        # its own, so the range falls back to the nearest block that has one.
        paragraph_from=_paragraph(blocks, first.page, forwards=True),
        paragraph_to=_paragraph(blocks, last.page, forwards=False),
    )


def _paragraph(blocks: list[TextBlock], page: int, *, forwards: bool) -> int:
    """The first or last numbered paragraph on `page` within these blocks."""
    on_page = [b.paragraph for b in blocks if b.page == page and b.paragraph is not None]
    if not on_page:
        return 0
    return on_page[0] if forwards else on_page[-1]


def _length(blocks: list[TextBlock]) -> int:
    return sum(len(block.text) for block in blocks)


def _section_number(title: str) -> str:
    """The number out of a heading like '2.1. Rechtliche Grundlagen'."""
    match = _SECTION_NUMBER_RE.match(title)
    return match.group(1).rstrip(".") if match else ""
