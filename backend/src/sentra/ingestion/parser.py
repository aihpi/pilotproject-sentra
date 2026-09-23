import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium
from docling.document_converter import DocumentConverter
from docling_core.types.doc.document import ContentLayer, DoclingDocument

logger = logging.getLogger(__name__)


# Which Docling labels are body text, for the purpose of counting paragraphs.
#
# A judgement rather than a detail. `section_header` is a heading, `footnote`
# and `caption` are apparatus — counting them as paragraphs would shift the
# numbering on exactly the pages that carry the most citations, which are the
# pages a 4.3a check is most likely to be about. Measured on WD 5-077-23.pdf:
# 177 text, 33 section_header, 14 list_item, 14 footnote, 4 caption.
BODY_LABELS = frozenset({"text", "list_item"})


@dataclass(frozen=True)
class TextBlock:
    """One item of a document, with where it sits.

    `paragraph` counts body blocks on the page, from 1, and is None for
    anything that is not body text. Per page rather than per document because
    "page 4, third paragraph" is something a reviewer holding the PDF can
    verify by counting — and 4.3a is answered by a human, not by a tool.
    """

    text: str
    label: str
    page: int
    paragraph: int | None


@dataclass
class ParsedDocument:
    """A PDF document parsed by Docling."""

    source_file: str
    markdown: str
    furniture_text: str  # page headers/footers — used for metadata extraction
    pdf_metadata: dict = field(default_factory=dict)
    # The same body, item by item, with page and paragraph. Markdown stays:
    # metadata extraction reads it, and the export is the only thing that knows
    # how to render a table as text. What the export cannot do is say where any
    # of it came from, which is why both exist.
    blocks: list["TextBlock"] = field(default_factory=list)


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
                blocks=_blocks_of(doc),
            )
            logger.info(
                "Parsed %s (%d chars body, %d chars furniture)",
                source,
                len(markdown),
                len(furniture_text),
            )
        except Exception:
            logger.exception("Failed to process %s", source)

    logger.info("Finished parsing documents from %s", documents_dir)


def number_paragraphs(items: Iterable[tuple[str, str, int]]) -> list[TextBlock]:
    """Turn `(text, label, page)` into blocks, numbering body paragraphs.

    Pure, and separate from walking a DoclingDocument on purpose: Docling is 5
    to 20 seconds a document, so anything that needs it is an integration test
    and effectively untested in CI. The decisions live here — what counts as a
    paragraph, and where the count restarts — so this is the part CI runs.

    The counter restarts on every page. It does not restart per section: a
    section can span a page break, and a reviewer counting paragraphs is
    counting down a page, not down a section.

    **Number first, filter later.** Whatever eventually drops boilerplate — the
    disclaimer block, the repeated headers — has to do it *after* this, not
    before. A reviewer counting down page 2 counts the disclaimer along with
    everything else, because it is printed there; numbering the survivors would
    produce citations that are internally consistent and do not match the paper
    in front of them. Observed on WD 10-042-22.pdf, where the disclaimer is
    page 2 paragraph 2.
    """
    blocks: list[TextBlock] = []
    counter = 0
    current_page: int | None = None

    for text, label, page in items:
        if page != current_page:
            current_page = page
            counter = 0

        if label in BODY_LABELS:
            counter += 1
            paragraph: int | None = counter
        else:
            paragraph = None

        blocks.append(TextBlock(text=text, label=label, page=page, paragraph=paragraph))

    return blocks


def _blocks_of(doc: DoclingDocument) -> list[TextBlock]:
    """Every text item of a document, in reading order, with its provenance.

    An item with no provenance is skipped rather than guessed at. It happens —
    a synthesised item, or one Docling could not place — and a citation
    pointing at page 0 is worse than one that does not exist.
    """
    items: list[tuple[str, str, int]] = []
    for item, _level in doc.iterate_items():
        text = getattr(item, "text", None)
        if not text or not text.strip():
            continue
        prov = list(getattr(item, "prov", []) or [])
        if not prov or prov[0].page_no is None:
            continue
        items.append((text, str(getattr(item, "label", "")), int(prov[0].page_no)))

    return number_paragraphs(items)


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


def _extract_furniture_text(doc: DoclingDocument) -> str:
    """Extract all furniture-layer items (page headers/footers) as a single text block."""
    lines: list[str] = []
    for item, _level in doc.iterate_items(
        included_content_layers={ContentLayer.FURNITURE},
    ):
        text = item.text if hasattr(item, "text") else ""
        if text and text.strip():
            lines.append(text.strip())
    return "\n".join(lines)
