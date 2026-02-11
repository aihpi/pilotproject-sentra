import logging
from dataclasses import dataclass
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling_core.types.doc.document import ContentLayer

logger = logging.getLogger(__name__)


@dataclass
class ParsedDocument:
    """A PDF document parsed by Docling."""

    source_file: str
    markdown: str
    furniture_text: str  # page headers/footers — used for metadata extraction


def parse_pdfs(documents_dir: str) -> list[ParsedDocument]:
    """Parse all PDFs in a directory using Docling.

    Returns a list of ParsedDocument with:
    - markdown: body content (for chunking and embedding)
    - furniture_text: page headers/footers (for metadata extraction)

    Documents that fail to parse are logged and skipped.
    """
    pdf_dir = Path(documents_dir)
    pdf_paths = sorted(pdf_dir.glob("*.pdf"))

    if not pdf_paths:
        logger.warning("No PDF files found in %s", documents_dir)
        return []

    logger.info("Parsing %d PDF files from %s", len(pdf_paths), documents_dir)
    converter = DocumentConverter()
    results: list[ParsedDocument] = []

    for conv_result in converter.convert_all(pdf_paths, raises_on_error=False):
        source = conv_result.input.file.name if conv_result.input.file else "unknown"
        try:
            doc = conv_result.document
            markdown = doc.export_to_markdown()
            furniture_text = _extract_furniture_text(doc)
            results.append(
                ParsedDocument(
                    source_file=source,
                    markdown=markdown,
                    furniture_text=furniture_text,
                )
            )
            logger.info("Parsed %s (%d chars body, %d chars furniture)", source, len(markdown), len(furniture_text))
        except Exception:
            logger.exception("Failed to process %s", source)

    logger.info("Successfully parsed %d / %d documents", len(results), len(pdf_paths))
    return results


def _extract_furniture_text(doc) -> str:
    """Extract all furniture-layer items (page headers/footers) as a single text block."""
    lines: list[str] = []
    for item, _level in doc.iterate_items(
        included_content_layers={ContentLayer.FURNITURE},
    ):
        text = item.text if hasattr(item, "text") else ""
        if text and text.strip():
            lines.append(text.strip())
    return "\n".join(lines)
