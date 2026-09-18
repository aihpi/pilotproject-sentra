"""Command line for the eval case file, and the templates cases arrive on.

    uv run python -m sentra_eval.cli export cases.yaml
    uv run python -m sentra_eval.cli import cases.yaml

A CLI rather than an endpoint, and in the same category as `alembic upgrade
head`: something an operator runs against a deployment, not something a browser
posts. It is also how a round's cases exist at all before there is a UI to
write them in.
"""

import argparse
import sys
from pathlib import Path

from sentra_eval import yaml_io
from sentra_eval.db import EvalDatabaseUnavailable, session_scope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentra-eval-cases", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    importer = sub.add_parser(
        "import", help="apply a case file, or a filled-in collection sheet, to the database"
    )
    importer.add_argument("file", type=Path, help="a .yaml case file or a .xlsx collection sheet")
    importer.add_argument(
        "--allow-new-ids",
        action="store_true",
        help=(
            "accept cases whose Test-ID does not exist yet, for seeding a fresh database "
            "from an exported file. Off by default so a typo in a Test-ID is an error "
            "rather than a new case."
        ),
    )
    importer.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change and write nothing",
    )

    templates = sub.add_parser(
        "vorlagen", help="write the Excel and Word collection templates for case authors"
    )
    templates.add_argument("directory", type=Path, nargs="?", default=Path("vorlagen"))

    exporter = sub.add_parser("export", help="write every case to a file, or to stdout")
    exporter.add_argument("file", type=Path, nargs="?")
    exporter.add_argument("--include-withdrawn", action="store_true")

    args = parser.parse_args(argv)

    try:
        if args.command == "import":
            return _import(args)
        if args.command == "vorlagen":
            return _vorlagen(args)
        return _export(args)
    except EvalDatabaseUnavailable as exc:
        print(f"The eval database is not reachable: {exc}", file=sys.stderr)
        return 2
    except yaml_io.CaseFileError as exc:
        print(f"{args.file}:\n{exc}", file=sys.stderr)
        return 1


def _import(args: argparse.Namespace) -> int:
    entries = _read(args.file)

    with session_scope() as session:
        report = yaml_io.apply(session, entries, allow_new_ids=args.allow_new_ids)
        if args.dry_run:
            # Rolling back rather than never writing: the report is only
            # accurate if the writes actually happened, since what a case
            # becomes depends on what is already there.
            session.rollback()
            print(f"dry run — would be: {report.summary()}")
            return 0

    print(report.summary())
    for test_id in report.created:
        print(f"  created  {test_id}")
    for test_id in report.updated:
        print(f"  updated  {test_id}")
    return 0


def _read(path: Path) -> list[yaml_io.CaseEntry]:
    """A case file, or a filled-in collection sheet.

    The same command for both on purpose. The people writing cases work in
    Excel and the harness reads YAML; making the operator convert between them
    by hand would put a manual step between the cases being written and the
    cases being testable, which is the step that does not get done.
    """
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        from sentra_eval import vorlagen

        return yaml_io.validate(vorlagen.read_workbook(path))
    return yaml_io.parse(path.read_text(encoding="utf-8"))


def _vorlagen(args: argparse.Namespace) -> int:
    from sentra_eval import vorlagen

    written = vorlagen.write_templates(args.directory)
    for path in written:
        print(f"  {path}")
    return 0


def _export(args: argparse.Namespace) -> int:
    with session_scope() as session:
        text = yaml_io.dump(session, include_withdrawn=args.include_withdrawn)

    if args.file is None:
        sys.stdout.write(text)
    else:
        args.file.write_text(text, encoding="utf-8")
        print(f"wrote {args.file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
