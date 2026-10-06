"""Putting a file onto the documents volume, and reading back what is there.

Until this existed, a document reached the corpus by `kubectl cp` and nothing
else. That is a dependency on cluster access for an act that is part of
running SENTRA rather than part of operating it, and the people running this
pilot do not have it — which is why the corpus went months without a document
being added, and why an ingest run reporting errors could not be told apart
from a volume with nothing on it.

Everything here treats the filename as hostile. It arrives in a multipart
header, chosen by whoever is uploading, and the destination is a directory
that ingestion walks and the API serves files out of by name.
"""

import logging
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

# What may be written. Matches documents.registry.READABLE_SUFFIXES rather
# than the narrower set ingestion indexes: a `.docx` is a document the
# registry records and a reviewer may want present, it is simply not
# searchable. VolumeFile.indexable reports that difference instead of this
# refusing the file.
ALLOWED_SUFFIXES = {".pdf", ".docx"}

# Only what ingestion's `*.pdf` glob will pick up.
INDEXABLE_SUFFIXES = {".pdf"}

MAX_FILE_BYTES = 100 * 1024 * 1024

# Written while an upload is in flight. Outside the suffix allowlist on
# purpose, so a `*.pdf` glob cannot see a file that is still arriving.
_PARTIAL_SUFFIX = ".part"


class RejectedUpload(Exception):
    """The file was not written, with a reason meant for the person who sent it."""


def safe_name(raw: str | None) -> str:
    """The bare filename, or raise.

    A filename is not a path, and this is the only place that distinction is
    enforced. `Path(raw).name` alone is not enough: it happily turns
    `../../etc/passwd` into `passwd`, which is a *silent* rewrite of what
    somebody asked for, and silently writing somewhere other than where you
    were told is how this goes wrong. So anything path-shaped is refused
    rather than repaired.
    """
    if not raw or not raw.strip():
        raise RejectedUpload("Die Datei hat keinen Namen.")

    name = raw.strip()

    # Backslash too: a Windows browser can send one, and the check has to
    # refuse what any reader might treat as a separator, not what this one
    # does.
    if "/" in name or "\\" in name or "\x00" in name:
        raise RejectedUpload("Der Dateiname darf keinen Pfad enthalten.")

    if name in {".", ".."} or name.startswith("."):
        raise RejectedUpload("Der Dateiname ist nicht zulässig.")

    if Path(name).name != name:
        raise RejectedUpload("Der Dateiname ist nicht zulässig.")

    if len(name) > 255:
        raise RejectedUpload("Der Dateiname ist zu lang.")

    # Control characters in a name that ends up in logs, in the registry, and
    # in a Content-Disposition header.
    if re.search(r"[\x00-\x1f\x7f]", name):
        raise RejectedUpload("Der Dateiname enthält unzulässige Zeichen.")

    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
        raise RejectedUpload(f"Nur {allowed} werden angenommen.")

    return name


def store(source: BinaryIO, raw_name: str | None, documents_dir: Path) -> tuple[str, int]:
    """Write one uploaded file into the documents directory.

    Returns its name and size. Raises RejectedUpload for anything refused.

    Written to a temporary name in the same directory and renamed into place,
    because ingestion globs this directory: a file still being written is a
    file Docling may open. `os.replace` is atomic within a filesystem, so the
    name either does not exist or is a complete document, never half of one.

    The same-directory part matters — a temporary file in /tmp would be on
    another filesystem and the rename would become a copy, which is not
    atomic and would put the half-written state back.
    """
    name = safe_name(raw_name)

    documents_dir.mkdir(parents=True, exist_ok=True)
    destination = documents_dir / name

    # Refused rather than overwritten. Same name with different content is a
    # change to a corpus that WD staff read as authoritative, and doing it as
    # a side effect of an upload is not a decision anybody made.
    if destination.exists():
        raise RejectedUpload("Eine Datei mit diesem Namen ist bereits vorhanden.")

    handle, temporary = tempfile.mkstemp(
        dir=documents_dir, prefix=".upload-", suffix=_PARTIAL_SUFFIX
    )
    written = 0
    try:
        with os.fdopen(handle, "wb") as out:
            while chunk := source.read(1024 * 1024):
                written += len(chunk)
                # Checked while streaming, not from a Content-Length the
                # sender chose. The cap exists to stop a 50Gi volume being
                # filled by accident, and a header cannot be trusted to
                # enforce it.
                if written > MAX_FILE_BYTES:
                    raise RejectedUpload(
                        f"Die Datei ist größer als {MAX_FILE_BYTES // (1024 * 1024)} MB."
                    )
                out.write(chunk)

        if written == 0:
            raise RejectedUpload("Die Datei ist leer.")

        # Re-checked immediately before the rename. Between the check above
        # and here another upload may have taken the name, and os.replace
        # would overwrite it without a word.
        if destination.exists():
            raise RejectedUpload("Eine Datei mit diesem Namen ist bereits vorhanden.")

        os.replace(temporary, destination)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise

    logger.info("Uploaded %s (%d bytes)", name, written)
    return name, written


def listing(documents_dir: Path) -> list[tuple[str, int, str, bool]]:
    """Every readable file on the volume: name, size, modified, indexable.

    A directory that does not exist is an empty list rather than an error. It
    means nothing has ever been put there, which is a true and useful answer
    and was the actual state of at least one environment this week.

    Partial uploads are skipped — they are not documents yet, and showing them
    would make a listing flicker while somebody is uploading.
    """
    if not documents_dir.is_dir():
        return []

    files = []
    for path in sorted(documents_dir.iterdir()):
        if not path.is_file() or path.name.endswith(_PARTIAL_SUFFIX):
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        stat = path.stat()
        files.append(
            (
                path.name,
                stat.st_size,
                datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                path.suffix.lower() in INDEXABLE_SUFFIXES,
            )
        )
    return files
