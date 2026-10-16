"""Test cases as a YAML file, both directions.

A case that lives only in a database is a case nobody reviews. In a file it
shows up as a diff in a pull request, which is the same scrutiny the rest of
the repository gets — and it is how the first cases for a round get written at
all, before there is a UI to write them in.

The file is the source of truth for content; the database owns identity. So:

  - a case with no `nummer` is new, and the backend allocates one
  - a case with a known `nummer` is compared against its latest version, and
    only a real difference writes anything
  - a case with an unknown `nummer` is refused, unless seeding is asked for
    explicitly, because inventing an identity is exactly what the counter
    exists to prevent

Tag and labels in the file are applied when it creates a case, and not to one
that exists: those are corrected on screen, and an older export would put the
old values back on every import (#300). A tag given for a new case counts as
set by hand.

Import is idempotent, which is what makes "the file is the source of truth"
true rather than aspirational: running it twice must not double every case's
version history, or the git diff stops corresponding to anything.
"""

from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.orm import Session

from sentra_eval import cases as case_store
from sentra_eval.bestand import Bestand
from sentra_eval.labels import LabelError, normalise_kategorie
from sentra_eval.models import FREIGEGEBEN, Case, CaseVersion

# The fields that make up a case's content. Identity (nummer, tag) and bookkeeping
# (timestamps, version numbers) are deliberately not here: those belong to the
# database, and a file that could set them could rewrite history.
CONTENT_FIELDS = (
    "ausgangsfrage",
    "abteilung",
    "erwartete_antwort",
    "referenz_korrekt",
    "referenz_falsch",
    "referenz_korrekt_az",
    "referenz_falsch_az",
    "grund_fuer_aufnahme",
    "grenzfall",
)


class CaseFileError(RuntimeError):
    """The file could not be applied. The message names the case and the field."""


class CaseEntry(BaseModel):
    """One case as it appears in the file."""

    # A key the importer does not know is refused rather than ignored: a typo
    # in a field name would otherwise drop that field silently, and a file
    # from before #285 would be read as all new cases (#300).
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _no_test_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and "test_id" in data:
            raise ValueError(
                "test_id gibt es seit #285 nicht mehr, die Identität ist `nummer`. "
                "Die Datei stammt von vorher: bitte neu exportieren."
            )
        return data

    # Absent for a new case: the backend allocates it and the next export adds
    # it. Writing one by hand is how a number gets reused.
    nummer: int | None = None
    tag: str = ""
    # An open list (#286): a built-in category or any short code.
    kategorie: str
    # Labels (#286), and the tag above: applied when the file creates a case,
    # never to one that exists. Labels are corrected on screen, and a file
    # exported before the correction would otherwise put the old value back
    # every time it is imported (#300). None means the file does not say.
    testart: str | None = None
    frageform: str | None = None
    herkunft: str | None = None
    ausgangsfrage: str = Field(min_length=1)
    abteilung: str = ""
    erwartete_antwort: str = ""
    referenz_korrekt: str = ""
    referenz_falsch: str = ""
    referenz_korrekt_az: str = ""
    referenz_falsch_az: str = ""
    grund_fuer_aufnahme: str = ""
    grenzfall: bool = False
    # entwurf | freigegeben. Approving from the file is deliberate: the pull
    # request that changed it is the review, which is the same act the UI's
    # approve button performs.
    status: str = "entwurf"

    @field_validator("kategorie")
    @classmethod
    def _kategorie(cls, value: str) -> str:
        try:
            return normalise_kategorie(value)
        except LabelError as exc:
            raise ValueError(str(exc)) from exc

    def content(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in CONTENT_FIELDS}

    def labels(self) -> dict[str, str]:
        """The labels the file gives, and only those."""
        return {
            name: value
            for name in ("testart", "frageform", "herkunft")
            if (value := getattr(self, name)) is not None
        }


@dataclass
class ImportReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    approved: list[str] = field(default_factory=list)
    bestand: Bestand | None = field(default=None, repr=False)

    @property
    def wrote_anything(self) -> bool:
        return bool(self.created or self.updated or self.approved)

    def summary(self) -> str:
        return (
            f"{len(self.created)} created, {len(self.updated)} updated, "
            f"{len(self.unchanged)} unchanged, {len(self.approved)} approved"
        )


# ── Reading a file ──────────────────────────────────────────────────


def parse(text: str) -> list[CaseEntry]:
    """Validate the file, naming the case and field for anything wrong.

    A pydantic ValidationError printed raw tells whoever wrote the file about
    `loc` and `input_value`. They wrote YAML; they should be told which case
    and which key.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CaseFileError(f"The file is not valid YAML: {exc}") from exc

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CaseFileError(
            "The file must be a list of cases, starting with '- kategorie: ...'. "
            f"Found {type(raw).__name__}."
        )

    return validate(raw)


def validate(raw: list[Any]) -> list[CaseEntry]:
    """The same validation, from records rather than from YAML text.

    Separate so the Excel collection sheet reaches the identical checks and the
    identical error shape — a case that would be rejected from a file has to be
    rejected from a spreadsheet, for the same stated reason, or the two
    on-ramps disagree about what a valid case is.
    """
    entries: list[CaseEntry] = []
    problems: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            problems.append(f"entry {index + 1}: expected a mapping, found {type(item).__name__}")
            continue
        name = f"Nr. {item['nummer']}" if item.get("nummer") else f"entry {index + 1}"
        try:
            entries.append(CaseEntry.model_validate(item))
        except ValidationError as exc:
            for error in exc.errors():
                location = ".".join(str(part) for part in error["loc"]) or "(case)"
                problems.append(f"{name}: {location}: {error['msg']}")

    if problems:
        raise CaseFileError("\n".join(problems))
    return entries


# ── Applying it ─────────────────────────────────────────────────────


def apply(
    session: Session,
    entries: list[CaseEntry],
    *,
    allow_new_ids: bool = False,
    bestand: Bestand | None = None,
) -> ImportReport:
    """Bring the database in line with the file.

    Writes nothing for a case whose content already matches, which is what
    makes running this twice safe.

    `bestand` is what an approval in the file is checked against (#257). The
    CLI passes one whenever the file approves anything.
    """
    report = ImportReport(bestand=bestand)
    for entry in entries:
        if entry.nummer is None:
            _create(session, entry, report)
        else:
            _update(session, entry, report, allow_new_ids=allow_new_ids)
    return report


def _create(session: Session, entry: CaseEntry, report: ImportReport) -> None:
    given = entry.labels()
    case, version = case_store.create_case(
        session,
        kategorie=entry.kategorie,
        testart=given.get("testart", ""),
        frageform=given.get("frageform", ""),
        herkunft=given.get("herkunft", "manuell"),
        **entry.content(),
    )
    _tag_if_given(session, entry, case)
    report.created.append(case.tag)
    _approve_if_asked(session, entry, case, version, report)


def _update(
    session: Session, entry: CaseEntry, report: ImportReport, *, allow_new_ids: bool
) -> None:
    assert entry.nummer is not None
    try:
        case = case_store.get_case(session, entry.nummer)
    except case_store.UnknownCase as exc:
        if not allow_new_ids:
            raise CaseFileError(
                f"Nr. {entry.nummer}: no such case. Numbers are allocated by the backend, so a "
                f"new case is written without one. If you are seeding a fresh database from an "
                f"exported file, pass --allow-new-ids."
            ) from exc
        try:
            case, version = case_store.seed_case(
                session,
                nummer=entry.nummer,
                tag=entry.tag,
                kategorie=entry.kategorie,
                **entry.labels(),
                **entry.content(),
            )
        except case_store.CaseError as seed_exc:
            raise CaseFileError(f"Nr. {entry.nummer}: {seed_exc}") from seed_exc
        report.created.append(case.tag)
        _approve_if_asked(session, entry, case, version, report)
        return

    latest = case.versions[-1]
    if _content_of(latest) == entry.content():
        # Identical content. The only thing left that could differ is approval,
        # which is a state change rather than a content one.
        if entry.status == FREIGEGEBEN and not latest.is_approved:
            _approve(session, case, latest, report)
        else:
            report.unchanged.append(case.tag)
        return

    if latest.is_approved:
        version = case_store.add_version(session, case, **entry.content())
    else:
        version = case_store.edit_draft(session, latest, **entry.content())
    report.updated.append(case.tag)
    _approve_if_asked(session, entry, case, version, report)


def _approve_if_asked(
    session: Session, entry: CaseEntry, case: Case, version: CaseVersion, report: ImportReport
) -> None:
    if entry.status == FREIGEGEBEN:
        _approve(session, case, version, report)


def _approve(session: Session, case: Case, version: CaseVersion, report: ImportReport) -> None:
    try:
        case_store.approve(session, version, bestand=report.bestand)
    except case_store.IncompleteCase as exc:
        raise CaseFileError(str(exc)) from exc
    report.approved.append(case.tag)


def _tag_if_given(session: Session, entry: CaseEntry, case: Case) -> bool:
    """Apply the file's tag if it has one that differs. Whether it did."""
    tag = entry.tag.strip()
    if not tag or tag == case.tag:
        return False
    try:
        case_store.set_tag(session, case, tag)
    except case_store.TagTaken as exc:
        raise CaseFileError(f"Nr. {case.nummer}: {exc}") from exc
    return True


def _content_of(version: CaseVersion) -> dict[str, Any]:
    return {name: getattr(version, name) for name in CONTENT_FIELDS}


# ── Writing a file ──────────────────────────────────────────────────


def dump(session: Session, *, include_withdrawn: bool = False) -> str:
    """Every case as YAML, latest version each, ready to re-import unchanged."""
    entries = []
    for case in case_store.list_cases(session, include_withdrawn=include_withdrawn):
        latest = case.versions[-1]
        entries.append(
            {
                "nummer": case.nummer,
                "tag": case.tag,
                "kategorie": case.kategorie,
                "testart": case.testart,
                "frageform": case.frageform,
                "herkunft": case.herkunft,
                **_content_of(latest),
                "status": latest.status,
            }
        )
    return yaml.safe_dump(
        entries,
        allow_unicode=True,  # the questions and answers are German
        sort_keys=False,  # the field order above is the order a person reads
        default_flow_style=False,
        width=88,
    )
