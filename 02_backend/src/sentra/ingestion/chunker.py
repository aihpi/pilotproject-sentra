import logging
import re
from dataclasses import dataclass

from sentra.ingestion.metadata import DocumentMetadata

logger = logging.getLogger(__name__)

# Patterns for boilerplate to strip
_BOILERPLATE_PATTERNS = [
    # End-of-document marker
    re.compile(r"\n\*\*\*\s*$"),
    # Copyright line
    re.compile(r"©\s*\d{4}\s*Deutscher Bundestag"),
    # Disclaimer block (duplicated by Docling from two-column layout)
    re.compile(
        r"Die Wissenschaftlichen Dienste des Deutschen Bundestages unterstützen"
        r".+?Der Fachbereich berät über die dabei zu berücksichtigenden Fragen\.",
        re.DOTALL,
    ),
    # Repeated Wissenschaftliche Dienste header lines
    re.compile(
        r"^#+\s*Wissenschaftliche Dienste\s+Wissenschaftliche Dienste\s*$",
        re.MULTILINE,
    ),
    # "Deutscher Bundestag" standalone heading
    re.compile(r"^#+\s*Deutscher Bundestag\s*$", re.MULTILINE),
    # Image placeholders
    re.compile(r"<!--\s*image\s*-->"),
]

# Markdown header pattern
_SECTION_HEADER_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


@dataclass
class Chunk:
    """A text chunk from a Bundestag document, ready for embedding."""

    text: str
    section_title: str
    section_path: str
    chunk_index: int
    metadata: DocumentMetadata


def chunk_document(
    markdown: str, metadata: DocumentMetadata, max_tokens: int = 2048
) -> list[Chunk]:
    """Split a Docling Markdown document into chunks based on section headers.

    Strategy:
    - Strip boilerplate (disclaimers, repeated headers, image placeholders)
    - Split on Markdown headers (##, ###) as section boundaries
    - Short documents (Kurzinformation) kept as a single chunk
    - Large sections split on paragraph boundaries as safety net
    - Footnotes stay attached to their parent section
    """
    cleaned = _strip_boilerplate(markdown)

    # For short documents (Kurzinformation), return as single chunk
    if metadata.document_type == "Kurzinformation" or len(cleaned) < 1000:
        text = cleaned.strip()
        if not text:
            return []
        return [
            Chunk(
                text=text,
                section_title=metadata.title,
                section_path="",
                chunk_index=0,
                metadata=metadata,
            )
        ]

    sections = _split_into_sections(cleaned)

    chunks: list[Chunk] = []
    for idx, (title, path, text) in enumerate(sections):
        text = text.strip()
        if not text or len(text) < 30:
            continue

        # Approximate token count (1 token ≈ 4 chars for German text)
        approx_tokens = len(text) // 4

        if approx_tokens <= max_tokens:
            chunks.append(
                Chunk(
                    text=text,
                    section_title=title,
                    section_path=path,
                    chunk_index=idx,
                    metadata=metadata,
                )
            )
        else:
            # Split oversized sections on paragraph boundaries
            sub_chunks = _split_on_paragraphs(text, max_tokens)
            for sub_idx, sub_text in enumerate(sub_chunks):
                chunks.append(
                    Chunk(
                        text=sub_text,
                        section_title=f"{title} (Teil {sub_idx + 1})" if len(sub_chunks) > 1 else title,
                        section_path=path,
                        chunk_index=idx,
                        metadata=metadata,
                    )
                )

    # Re-number sequentially so chunk_index is unique per document
    # (paragraph sub-chunks from oversized sections share the section's idx above)
    for i, chunk in enumerate(chunks):
        chunk.chunk_index = i

    logger.info(
        "Chunked %s into %d chunks (source: %s)",
        metadata.aktenzeichen or metadata.title,
        len(chunks),
        metadata.source_file,
    )
    return chunks


def _strip_boilerplate(markdown: str) -> str:
    """Remove known boilerplate patterns from the Markdown."""
    result = markdown
    for pattern in _BOILERPLATE_PATTERNS:
        result = pattern.sub("", result)
    # Collapse multiple blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _split_into_sections(markdown: str) -> list[tuple[str, str, str]]:
    """Split Markdown into sections based on headers.

    Returns list of (section_title, section_path, section_text) tuples.
    """
    headers = list(_SECTION_HEADER_RE.finditer(markdown))

    if not headers:
        return [("Inhalt", "", markdown)]

    sections: list[tuple[str, str, str]] = []

    # Content before first header
    preamble = markdown[: headers[0].start()].strip()
    if preamble and len(preamble) > 50:
        sections.append(("Einleitung", "", preamble))

    for i, match in enumerate(headers):
        title = match.group(2).strip()

        # Skip ToC heading and metadata headings
        title_lower = title.lower()
        if title_lower in ("inhaltsverzeichnis", "aktenzeichen"):
            continue
        if title_lower.startswith("aktenzeichen:"):
            continue

        path = _extract_section_number(title)
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(markdown)
        body = markdown[start:end].strip()

        # Include heading for context
        full_text = f"{title}\n\n{body}" if body else title
        sections.append((title, path, full_text))

    return sections


def _extract_section_number(title: str) -> str:
    """Extract section number from title like '2.1. Rechtliche Grundlagen'."""
    match = re.match(r"^([\d.]+\.?)\s", title)
    return match.group(1).rstrip(".") if match else ""


def _split_on_paragraphs(text: str, max_tokens: int) -> list[str]:
    """Split text on paragraph boundaries to stay within token limit."""
    paragraphs = re.split(r"\n\n+", text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_tokens = len(para) // 4
        if current_len + para_tokens > max_tokens and current:
            chunks.append("\n\n".join(current))
            current = [para]
            current_len = para_tokens
        else:
            current.append(para)
            current_len += para_tokens

    if current:
        chunks.append("\n\n".join(current))

    return chunks
