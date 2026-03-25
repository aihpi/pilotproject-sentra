import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium
from docling.document_converter import DocumentConverter
from docling_core.types.doc.document import ContentLayer

logger = logging.getLogger(__name__)


@dataclass
class ParsedDocument:
    """A PDF document parsed by Docling."""

    source_file: str
    markdown: str
    furniture_text: str  # page headers/footers — used for metadata extraction
    pdf_metadata: dict = field(default_factory=dict)


def parse_pdfs(
    documents_dir: str,
    pdf_paths: list[Path] | None = None,
) -> Iterator[ParsedDocument]:
    """Parse PDFs using Docling.

    Yields ParsedDocument one at a time to limit memory usage.
    Each document contains:
    - markdown: body content (for chunking and embedding)
    - furniture_text: page headers/footers (for metadata extraction)
    - pdf_metadata: embedded PDF metadata (CreationDate, etc.)

    If pdf_paths is provided, only those files are processed (for incremental ingestion).
    Otherwise, all *.pdf files in documents_dir are processed.

    Documents that fail to parse are logged and skipped.
    """
    if pdf_paths is None:
        pdf_dir = Path(documents_dir)
        pdf_paths = sorted(pdf_dir.glob("*.pdf"))

    if not pdf_paths:
        logger.warning("No PDF files found in %s", documents_dir)
        return

    # Pre-extract PDF metadata using pypdfium2 (before Docling converts)
    metadata_by_name: dict[str, dict] = {}
    for pdf_path in pdf_paths:
        metadata_by_name[pdf_path.name] = _extract_pdf_metadata(pdf_path)

    logger.info("Parsing %d PDF files from %s", len(pdf_paths), documents_dir)
    converter = DocumentConverter()

    for conv_result in converter.convert_all(pdf_paths, raises_on_error=False):
        source = conv_result.input.file.name if conv_result.input.file else "unknown"
        try:
            doc = conv_result.document
            markdown = doc.export_to_markdown()
            furniture_text = _extract_furniture_text(doc)
            yield ParsedDocument(
                source_file=source,
                markdown=markdown,
                furniture_text=furniture_text,
                pdf_metadata=metadata_by_name.get(source, {}),
            )
            logger.info("Parsed %s (%d chars body, %d chars furniture)", source, len(markdown), len(furniture_text))
        except Exception:
            logger.exception("Failed to process %s", source)

    logger.info("Finished parsing documents from %s", documents_dir)


def _extract_pdf_metadata(pdf_path: Path) -> dict:
    """Extract embedded metadata from a PDF using pypdfium2."""
    try:
        doc = pdfium.PdfDocument(pdf_path)
        metadata = doc.get_metadata_dict()
        doc.close()
        return metadata
    except Exception:
        logger.debug("Could not read PDF metadata from %s", pdf_path.name)
        return {}


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
