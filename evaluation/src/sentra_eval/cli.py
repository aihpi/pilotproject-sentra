"""Command line for the eval case file.

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

    importer = sub.add_parser("import", help="apply a case file to the database")
    importer.add_argument("file", type=Path)
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

    exporter = sub.add_parser("export", help="write every case to a file, or to stdout")
    exporter.add_argument("file", type=Path, nargs="?")
    exporter.add_argument("--include-withdrawn", action="store_true")

    args = parser.parse_args(argv)

    try:
        if args.command == "import":
            return _import(args)
        return _export(args)
    except EvalDatabaseUnavailable as exc:
        print(f"The eval database is not reachable: {exc}", file=sys.stderr)
        return 2
    except yaml_io.CaseFileError as exc:
        print(f"{args.file}:\n{exc}", file=sys.stderr)
        return 1


def _import(args: argparse.Namespace) -> int:
    entries = yaml_io.parse(args.file.read_text(encoding="utf-8"))

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
