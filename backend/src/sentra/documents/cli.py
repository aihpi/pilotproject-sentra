"""Scan the corpus into the registry, and say what it found.

    uv run python -m sentra.documents.cli scan
    uv run python -m sentra.documents.cli scan --root ../data/Ausarbeitungen
    uv run python -m sentra.documents.cli drift

A CLI rather than an endpoint, and in the same category as `alembic upgrade
head`: something an operator runs against a deployment, not something a browser
posts. `POST /api/documents/import` comes with the job queue in task 3, because
a scan of 1919 files is not a request that waits for its own result.

The report is the deliverable. Everything else this task builds exists so the
numbers can be produced again next week and compared.
"""

import argparse
import logging
import sys
from pathlib import Path

from sentra.config import get_settings
from sentra.db import RegistryDatabaseUnavailable, session_scope
from sentra.documents import registry
from sentra.rag.store import VectorStore

logger = logging.getLogger(__name__)


def _indexed_metadata() -> dict[str, dict]:
    """What the index already knows, keyed by filename.

    The scan works without this — Qdrant may be empty, or down — but with it
    the registry is useful immediately instead of after hours of Docling. It is
    only ever used to fill fields that are empty.
    """
    try:
        store = VectorStore(get_settings())
        return {
            record.source_file: {
                "title": record.title,
                "fachbereich": record.fachbereich,
                "fachbereich_number": record.fachbereich_number,
                "document_type": record.document_type,
                "completion_date": record.completion_date,
                "language": record.language,
            }
            for record in store.scroll_all_documents()
            if record.source_file
        }
    except Exception as exc:  # noqa: BLE001 - the scan is useful without it
        logger.warning("Could not read the index, scanning without it: %s", exc)
        return {}


def _print_scan(report: registry.ScanReport) -> None:
    print(report.summary())
    print()
    print("  by type          ", ", ".join(f"{k} {v}" for k, v in sorted(report.by_suffix.items())))
    print(f"  needs review      {report.needs_review}")
    print()

    print(f"  duplicate content {len(report.duplicate_hashes)}")
    for names in list(report.duplicate_hashes.values())[:10]:
        print(f"      {' == '.join(names)}")

    print(f"  colliding names   {len(report.colliding_names)}")
    for name, count in list(report.colliding_names.items())[:10]:
        print(f"      {name} ×{count}")

    print(f"  no Aktenzeichen   {len(report.unreadable_names)}")
    for name in report.unreadable_names[:10]:
        print(f"      {name}")

    print(f"  several AZ        {len(report.multiple_aktenzeichen)}")
    for name, found in list(report.multiple_aktenzeichen.items())[:10]:
        print(f"      {name} → {', '.join(found)}")
    print(
        f"  → {report.recovered_aktenzeichen} Aktenzeichen recorded that the ingestion path drops"
    )


def _print_drift(found: registry.Drift) -> None:
    print(f"  agreed              {found.agreed}")
    print(f"  indexed, no row     {len(found.indexed_without_row)}")
    for name in found.indexed_without_row[:25]:
        print(f"      {name}")
    print(f"  row, no chunks      {len(found.row_without_chunks)}")
    for name in found.row_without_chunks[:25]:
        print(f"      {name}")
    if found.indexed_without_row:
        print()
        print(
            "  Indexed documents with no registry row are citable with nothing\n"
            "  behind them: the source card 404s. See #140 — repairing them needs\n"
            "  the point-id change in task 2, so this reports and does not act."
        )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="walk the corpus into the registry")
    scan_parser.add_argument(
        "--root", default=None, help="defaults to the configured documents_dir"
    )
    scan_parser.add_argument(
        "--no-enrichment",
        action="store_true",
        help="do not read metadata from the index",
    )

    sub.add_parser("drift", help="compare the registry against the index")

    args = parser.parse_args(argv)
    settings = get_settings()

    try:
        if args.command == "scan":
            root = Path(args.root or settings.documents_dir)
            if not root.is_dir():
                print(f"Not a directory: {root}", file=sys.stderr)
                return 2
            known = {} if args.no_enrichment else _indexed_metadata()
            with session_scope() as session:
                report = registry.scan(session, root, known=known)
            _print_scan(report)
            return 0

        indexed = _indexed_metadata()
        with session_scope() as session:
            found = registry.drift(session, indexed)
        _print_drift(found)
        return 0 if found.is_clean else 1
    except RegistryDatabaseUnavailable as exc:
        print(f"The registry database is not reachable: {exc}", file=sys.stderr)
        print("Start it with: docker compose up -d sentra-db", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
