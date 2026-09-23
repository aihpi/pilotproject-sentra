"""Filling the registry by looking at the corpus, and changing nothing.

Read-only in the sense that matters: it writes registry rows and does not touch
Qdrant. Running it against a live deployment is safe, which is the point of
doing it before anything else — `docs/SOURCE_MANAGEMENT_NOTES.md` puts it first
because it tells us more about this corpus than more design will.

Two things it deliberately does not do.

It does not parse. `metadata.py` needs Docling-converted Markdown, and Docling
is 5 to 20 seconds a document against 1919 of them: hours, for a scan whose
value is being runnable now and repeatedly. What it extracts instead is what
the filename carries, plus what the existing index already knows, joined on the
filename Qdrant payloads already key on. The registry is therefore useful on
day one and gets its real metadata when documents are actually re-parsed.

It does not index, delete or repair. The drift it measures is reported, not
acted on. Deciding what to do about 17 citable documents with no file behind
them is #140, and doing it needs the point-id change in task 2.
"""

import hashlib
import logging
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sentra.documents.models import (
    FOLDER_IMPORT,
    NEEDS_REVIEW,
    PENDING,
    Document,
    DocumentAktenzeichen,
    DocumentFile,
)
from sentra.ingestion.metadata import _format_az

logger = logging.getLogger(__name__)

# Same shape as metadata._FILENAME_RE, used with finditer rather than search.
# That single difference is what recovers the 68 Aktenzeichen the corpus has
# and the ingestion path drops: 65 joint documents name 133 between them, and
# `search` keeps the first.
_FILENAME_AZ_RE = re.compile(r"((?:WD|EU)\s*\d+)-(\d+)-(\d+)")

# What the scan will look at. `.docx` is included so the 23 abstracts sitting
# beside the PDFs stop being invisible — every glob in the codebase is `*.pdf`,
# so nothing has ever reported that they exist. Recording them is not admitting
# them: nothing here indexes anything, and whether they belong in the corpus is
# an open question in #141 that this scan is meant to inform.
READABLE_SUFFIXES = {".pdf", ".docx"}

_HASH_CHUNK = 1024 * 1024

# What a usable value looks like. Both of these are things the index currently
# gets wrong on joint documents, and neither was checkable before there was a
# registry to compare against.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FACHBEREICH_NUMBER_RE = re.compile(r"^(?:WD|EU|PE)\s*\d+$")


@dataclass
class ScanReport:
    """What the corpus turned out to contain.

    The numbers are the deliverable. Everything else this task builds exists so
    that these can be produced again next week and compared.
    """

    scanned: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0

    duplicate_hashes: dict[str, list[str]] = field(default_factory=dict)
    colliding_names: dict[str, int] = field(default_factory=dict)
    unreadable_names: list[str] = field(default_factory=list)
    multiple_aktenzeichen: dict[str, list[str]] = field(default_factory=dict)
    by_suffix: dict[str, int] = field(default_factory=dict)
    needs_review: int = 0

    # What the index claims and could not be true. Not the scan's fault and not
    # the scan's to fix — the point is that until now nothing compared these
    # against anything, so nobody knew.
    bad_completion_date: dict[str, str] = field(default_factory=dict)
    bad_fachbereich_number: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"{self.scanned} scanned, {self.created} created, "
            f"{self.updated} updated, {self.unchanged} unchanged"
        )

    @property
    def recovered_aktenzeichen(self) -> int:
        """Aktenzeichen this scan recorded that the ingestion path would drop.

        One per extra Aktenzeichen on a joint document — the measurement behind
        "68 silently dropped" in the notes, recomputed rather than quoted.
        """
        return sum(len(found) - 1 for found in self.multiple_aktenzeichen.values())


@dataclass
class Drift:
    """Where the registry and the index disagree.

    Both directions, because they fail differently. A document indexed with no
    registry row is citable with nothing behind it — #140, and the one a user
    meets as a 404. A registry row with no chunks is a document nobody can find,
    which is quieter and worse to discover late.
    """

    indexed_without_row: list[str] = field(default_factory=list)
    row_without_chunks: list[str] = field(default_factory=list)
    agreed: int = 0

    @property
    def is_clean(self) -> bool:
        return not self.indexed_without_row and not self.row_without_chunks


def aktenzeichen_in(name: str) -> list[str]:
    """Every Aktenzeichen a filename carries, in the order it carries them.

    `WD 1-019-24; WD 7-060-24.pdf` gives two. The ingestion path gives one.
    """
    return [
        _format_az(match.group(1), f"{match.group(2)}/{match.group(3)}")
        for match in _FILENAME_AZ_RE.finditer(name)
    ]


def hash_file(path: Path) -> str:
    """sha256 of the bytes, streamed. 592 MB of corpus does not fit in memory
    twice, and identity has to be the content rather than the name: 30 names
    collide across the original tree."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def walk(root: Path) -> Iterator[Path]:
    """Every readable file under root, recursively.

    Recursive on purpose. `glob("*.pdf")` is not, which is how ~1950 files in
    `03_data/Extra/ab_2023/` were invisible until the tree was flattened by
    hand. The flattening made the non-recursive glob correct by accident, and
    it stays correct only until somebody adds a subdirectory.
    """
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in READABLE_SUFFIXES:
            yield path


def scan(session: Session, root: Path, *, known: dict[str, dict] | None = None) -> ScanReport:
    """Bring the registry in line with what is on disk.

    Idempotent by content hash: running it twice writes nothing the second
    time, which is what makes it safe to run on a schedule and what lets the
    numbers be compared between runs.

    `known` is metadata the index already holds, keyed by filename. Optional,
    because the scan has to work against an empty or unreachable Qdrant — a
    registry that cannot be built without the thing it is meant to become the
    source of truth for would be the wrong way round.
    """
    report = ScanReport()
    known = known or {}

    seen_hashes: dict[str, str] = {}
    names: Counter[str] = Counter()

    for path in walk(root):
        report.scanned += 1
        suffix = path.suffix.lower()
        report.by_suffix[suffix] = report.by_suffix.get(suffix, 0) + 1
        names[path.name] += 1

        content_hash = hash_file(path)
        if content_hash in seen_hashes:
            report.duplicate_hashes.setdefault(content_hash, [seen_hashes[content_hash]]).append(
                str(path.name)
            )
            # Same bytes, second name. One document, two files — recorded
            # rather than dropped, so that a duplicate filing stays
            # distinguishable from a document that is simply not there.
            _attach_file(session, content_hash, path, root)
            continue
        seen_hashes[content_hash] = path.name

        found = aktenzeichen_in(path.name)
        if not found:
            report.unreadable_names.append(path.name)
        if len(found) > 1:
            report.multiple_aktenzeichen[path.name] = found

        _upsert(session, path, root, content_hash, found, known.get(path.name, {}), report)

    report.colliding_names = {name: count for name, count in names.items() if count > 1}
    report.needs_review = len(
        session.execute(select(Document.id).where(Document.status == NEEDS_REVIEW)).scalars().all()
    )
    return report


def _attach_file(session: Session, content_hash: str, path: Path, root: Path) -> None:
    """Record another file holding bytes the registry already has."""
    document = session.execute(
        select(Document).where(Document.content_hash == content_hash)
    ).scalar_one_or_none()
    if document is None:
        return
    storage_key = str(path.relative_to(root))
    known = {f.storage_key for f in document.files}
    if storage_key not in known:
        session.add(
            DocumentFile(document_id=document.id, storage_key=storage_key, original_name=path.name)
        )
        session.flush()


def _upsert(
    session: Session,
    path: Path,
    root: Path,
    content_hash: str,
    found: list[str],
    enrichment: dict,
    report: ScanReport,
) -> None:
    existing = session.execute(
        select(Document).where(Document.content_hash == content_hash)
    ).scalar_one_or_none()

    # A document with no readable Aktenzeichen cannot be cited or matched
    # against an eval case, so it is a human's problem rather than something to
    # guess at. 105 of these were counted in the notes.
    reasons = [] if found else ["Kein Aktenzeichen im Dateinamen"]

    suspect = suspect_fields(enrichment)
    for name, value in suspect.items():
        reasons.append(f"{name} unplausibel: {value[:80]}")
    if "completion_date" in suspect:
        report.bad_completion_date[path.name] = suspect["completion_date"]
    if "fachbereich_number" in suspect:
        report.bad_fachbereich_number[path.name] = suspect["fachbereich_number"]

    reason = "; ".join(reasons)[:512]
    status = NEEDS_REVIEW if reason else PENDING

    if existing is None:
        document = Document(
            content_hash=content_hash,
            storage_key=str(path.relative_to(root)),
            original_name=path.name,
            status=status,
            source=FOLDER_IMPORT,
            review_reason=reason,
            size_bytes=path.stat().st_size,
            file_type=path.suffix.lower().lstrip("."),
        )
        _apply_enrichment(document, enrichment)
        session.add(document)
        session.flush()
        session.add(
            DocumentFile(
                document_id=document.id,
                storage_key=document.storage_key,
                original_name=document.original_name,
            )
        )
        for index, az in enumerate(found):
            session.add(
                DocumentAktenzeichen(
                    document_id=document.id, aktenzeichen=az, is_primary=index == 0
                )
            )
        report.created += 1
        return

    # Seen before. The bytes are the same — that is what matched — so the only
    # things that can have changed are where it sits and what the index knows.
    changed = False
    storage_key = str(path.relative_to(root))
    if existing.storage_key != storage_key or existing.original_name != path.name:
        existing.storage_key = storage_key
        existing.original_name = path.name
        changed = True
    if _apply_enrichment(existing, enrichment):
        changed = True

    existing.seen_at = datetime.now(UTC)
    if changed:
        report.updated += 1
    else:
        report.unchanged += 1


def suspect_fields(enrichment: dict) -> dict[str, str]:
    """Values the index holds that cannot be what they claim to be.

    `completion_date` drives the date-range filter, so a document whose date is
    not a date silently falls out of every filtered search — quietly, and only
    for the documents whose metadata was hardest to extract in the first place.
    """
    found: dict[str, str] = {}

    date = (enrichment.get("completion_date") or "").strip()
    if date and not _ISO_DATE_RE.match(date):
        found["completion_date"] = date

    number = (enrichment.get("fachbereich_number") or "").strip()
    if number and not _FACHBEREICH_NUMBER_RE.match(number):
        found["fachbereich_number"] = number

    return found


def _apply_enrichment(document: Document, enrichment: dict) -> bool:
    """Fill the descriptive fields from what the index already knows.

    Only ever fills a field that is empty. The registry is going to become the
    source of truth, so letting the index overwrite a value already recorded
    would be the dependency pointing the wrong way — and the human `overrides`
    layer in task 5 has to be able to outrank this.
    """
    changed = False
    for field_name in (
        "title",
        "fachbereich",
        "fachbereich_number",
        "document_type",
        "completion_date",
        "language",
    ):
        value = (enrichment.get(field_name) or "").strip()
        if value and not getattr(document, field_name):
            setattr(document, field_name, value)
            changed = True
    return changed


def register_file(session: Session, path: Path, root: Path) -> UUID:
    """The id of the document these bytes are, creating a row if there is none.

    What ingestion calls, one file at a time, where `scan` walks a tree. Both
    identify a document the same way — by the hash of its contents — so a file
    the scan already recorded is recognised here rather than duplicated.

    Identity by content is the point. A point keyed on a filename cannot
    survive a rename: the old points stay behind, the new ones are written
    beside them, and nothing connects the two. That is #140 — seventeen
    documents indexed under names the flattening of `data/` later changed,
    still searchable and citable with no file behind them. The same bytes under
    a new name are the same document here, and its chunks replace themselves.
    """
    content_hash = hash_file(path)
    existing = session.execute(
        select(Document).where(Document.content_hash == content_hash)
    ).scalar_one_or_none()

    if existing is not None:
        # Known bytes. The name may have changed, and recording that is how the
        # registry stays able to tell a rename from a disappearance.
        _attach_file(session, content_hash, path, root)
        if existing.original_name != path.name:
            existing.original_name = path.name
            existing.storage_key = str(path.relative_to(root))
            session.flush()
        return existing.id

    found = aktenzeichen_in(path.name)
    document = Document(
        content_hash=content_hash,
        storage_key=str(path.relative_to(root)),
        original_name=path.name,
        status=NEEDS_REVIEW if not found else PENDING,
        source=FOLDER_IMPORT,
        review_reason="" if found else "Kein Aktenzeichen im Dateinamen",
        size_bytes=path.stat().st_size,
        file_type=path.suffix.lower().lstrip("."),
    )
    session.add(document)
    session.flush()
    session.add(
        DocumentFile(
            document_id=document.id,
            storage_key=document.storage_key,
            original_name=document.original_name,
        )
    )
    for index, az in enumerate(found):
        session.add(
            DocumentAktenzeichen(document_id=document.id, aktenzeichen=az, is_primary=index == 0)
        )
    session.flush()
    return document.id


def drift(session: Session, indexed_names: Iterable[str]) -> Drift:
    """Compare the registry against what Qdrant holds.

    A query and a set difference, rather than the hand-run diff that found
    #140. The whole reason the registry exists is that this was not answerable.
    """
    indexed = {name for name in indexed_names if name}

    # Every name the corpus knows a document by, not only the primary one. A
    # document filed twice is indexed under both names, and comparing against
    # one of them would report the other as orphaned — which is exactly the
    # finding this is meant to make trustworthy.
    rows = {
        name
        for (name,) in session.execute(
            select(DocumentFile.original_name)
            .join(Document, DocumentFile.document_id == Document.id)
            .where(Document.status != "withdrawn")
        ).all()
    }

    found = Drift()
    found.indexed_without_row = sorted(indexed - rows)
    found.row_without_chunks = sorted(rows - indexed)
    found.agreed = len(indexed & rows)
    return found
