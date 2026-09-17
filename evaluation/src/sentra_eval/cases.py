"""Reading and writing test cases.

Everything that enforces the immutability rules is here rather than in the
router, because the YAML import in the next task is a second writer and a guard
that lives in a request handler would not apply to it.
"""

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from sentra_eval.categories import Kategorie
from sentra_eval.models import ENTWURF, FREIGEGEBEN, Case, CaseVersion, TestIdSequence

# "TF-GO-014": the prefix, the category abbreviation, a three digit number.
TEST_ID_PATTERN = re.compile(r"TF-(?P<kategorie>[A-Z]{2})-(?P<number>\d{3,})")


class CaseError(RuntimeError):
    """A case operation the caller asked for that the rules do not allow."""


class ApprovedVersionIsImmutable(CaseError):
    """Someone tried to edit a version that has already been approved.

    The one rule the whole harness rests on. An approved version is what a run
    was measured against; changing it afterwards would let an expectation be
    fitted to the answer it was supposed to judge, which is precisely what the
    Vorlage's "formuliert bevor SENTRA getestet wird" exists to prevent.
    """


class IncompleteCase(CaseError):
    """A version cannot be approved because it is not a usable yardstick yet."""


class UnknownCase(CaseError):
    """No case with that Test-ID."""


# ── Test-ID allocation ──────────────────────────────────────────────


def allocate_test_id(session: Session, kategorie: Kategorie) -> str:
    """The next Test-ID for a category. Never returns the same one twice.

    The counter row is locked for the duration, so two imports running at once
    cannot both read the same next_number. Without the lock this is the classic
    read-modify-write race, and the symptom would be a unique-constraint error
    on test_id that looks like a bug in the caller.
    """
    row = session.execute(
        select(TestIdSequence).where(TestIdSequence.kategorie == kategorie).with_for_update()
    ).scalar_one_or_none()

    if row is None:
        row = TestIdSequence(kategorie=str(kategorie), next_number=1)
        session.add(row)
        session.flush()

    number = row.next_number
    row.next_number = number + 1
    session.flush()
    return f"TF-{kategorie}-{number:03d}"


# ── Writing ─────────────────────────────────────────────────────────


def create_case(
    session: Session,
    kategorie: Kategorie,
    ausgangsfrage: str,
    *,
    abteilung: str = "",
    erwartete_antwort: str = "",
    referenz_korrekt: str = "",
    referenz_falsch: str = "",
    referenz_korrekt_az: str = "",
    referenz_falsch_az: str = "",
    grund_fuer_aufnahme: str = "",
    grenzfall: bool = False,
) -> tuple[Case, CaseVersion]:
    """A new case with its first version, as a draft.

    Always a draft, even when every field is filled in. Approval is a separate
    act with its own timestamp, and collapsing the two would mean the audit
    trail could not distinguish "written and approved together" from "approved
    without anyone reading it".
    """
    case = Case(test_id=allocate_test_id(session, kategorie), kategorie=str(kategorie))
    session.add(case)
    session.flush()

    version = CaseVersion(
        case_id=case.id,
        version=1,
        status=ENTWURF,
        ausgangsfrage=ausgangsfrage,
        abteilung=abteilung,
        erwartete_antwort=erwartete_antwort,
        referenz_korrekt=referenz_korrekt,
        referenz_falsch=referenz_falsch,
        referenz_korrekt_az=referenz_korrekt_az,
        referenz_falsch_az=referenz_falsch_az,
        grund_fuer_aufnahme=grund_fuer_aufnahme,
        grenzfall=grenzfall,
    )
    session.add(version)
    session.flush()
    return case, version


def edit_draft(session: Session, version: CaseVersion, **fields: object) -> CaseVersion:
    """Change a draft in place. Refuses an approved version."""
    if version.is_approved:
        raise ApprovedVersionIsImmutable(
            f"{version.case.test_id} version {version.version} is approved. "
            f"Add a new version instead — an approved version is what runs were measured "
            f"against, and editing it would let the expectation follow the answer."
        )
    for name, value in fields.items():
        setattr(version, name, value)
    session.flush()
    return version


def add_version(session: Session, case: Case, **fields: object) -> CaseVersion:
    """A new draft version, starting from the latest one's content.

    This is what "editing" an approved case means. The previous version stays
    exactly as it was, so a run that referenced it still points at what it
    actually measured against.
    """
    latest = case.versions[-1]
    carried = {
        "ausgangsfrage": latest.ausgangsfrage,
        "abteilung": latest.abteilung,
        "erwartete_antwort": latest.erwartete_antwort,
        "referenz_korrekt": latest.referenz_korrekt,
        "referenz_falsch": latest.referenz_falsch,
        "referenz_korrekt_az": latest.referenz_korrekt_az,
        "referenz_falsch_az": latest.referenz_falsch_az,
        "grund_fuer_aufnahme": latest.grund_fuer_aufnahme,
        "grenzfall": latest.grenzfall,
    }
    carried.update({k: v for k, v in fields.items() if v is not None})

    version = CaseVersion(case_id=case.id, version=latest.version + 1, status=ENTWURF, **carried)
    session.add(version)
    session.flush()
    return version


def approve(session: Session, version: CaseVersion) -> CaseVersion:
    """Turn a draft into a yardstick.

    Refuses anything that could not actually be measured against. An approved
    version with no expected answer or no correct reference would pass every
    check by having nothing to check, which is worse than no case at all.
    """
    if version.is_approved:
        return version

    missing = [
        name
        for name, value in (
            ("erwartete Antwort", version.erwartete_antwort),
            ("Referenzquelle (korrekt)", version.referenz_korrekt),
        )
        if not value.strip()
    ]
    if missing:
        raise IncompleteCase(
            f"{version.case.test_id} version {version.version} cannot be approved: "
            f"{', '.join(missing)} is missing. An approved version is what every check "
            f"compares against."
        )

    version.status = FREIGEGEBEN
    version.freigegeben_at = datetime.now(UTC)
    session.flush()
    return version


def seed_case(
    session: Session, *, test_id: str, kategorie: Kategorie, **content: object
) -> tuple[Case, CaseVersion]:
    """Create a case at a Test-ID that was allocated elsewhere.

    For restoring an exported file into an empty database, and for nothing
    else. The counter is advanced past the number so it can never be handed out
    again — without that, seeding TF-GO-007 and then creating a case normally
    would produce a second TF-GO-007, which is the exact failure the allocator
    exists to prevent.

    Deliberately not reachable from the API. The import CLI asks for it with an
    explicit flag, so it cannot happen as a side effect of a normal import.
    """
    match = TEST_ID_PATTERN.fullmatch(test_id)
    if match is None or match.group("kategorie") != str(kategorie):
        raise CaseError(
            f"{test_id!r} is not a Test-ID for category {kategorie}. "
            f"Expected the form TF-{kategorie}-001."
        )

    case = Case(test_id=test_id, kategorie=str(kategorie))
    session.add(case)
    session.flush()

    number = int(match.group("number"))
    row = session.execute(
        select(TestIdSequence).where(TestIdSequence.kategorie == kategorie).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = TestIdSequence(kategorie=str(kategorie), next_number=number + 1)
        session.add(row)
    else:
        row.next_number = max(row.next_number, number + 1)

    version = CaseVersion(case_id=case.id, version=1, status=ENTWURF, **content)
    session.add(version)
    session.flush()
    return case, version


def withdraw(session: Session, case: Case) -> Case:
    """Take a case out of future rounds without freeing its Test-ID."""
    if case.zurueckgezogen_at is None:
        case.zurueckgezogen_at = datetime.now(UTC)
        session.flush()
    return case


# ── Reading ─────────────────────────────────────────────────────────


def list_cases(session: Session, *, include_withdrawn: bool = False) -> list[Case]:
    statement = select(Case).options(selectinload(Case.versions)).order_by(Case.test_id)
    if not include_withdrawn:
        statement = statement.where(Case.zurueckgezogen_at.is_(None))
    return list(session.execute(statement).scalars())


def get_case(session: Session, test_id: str) -> Case:
    case = session.execute(
        select(Case).options(selectinload(Case.versions)).where(Case.test_id == test_id)
    ).scalar_one_or_none()
    if case is None:
        raise UnknownCase(f"No case with Test-ID {test_id!r}.")
    return case


def latest_approved(case: Case) -> CaseVersion | None:
    """The version a run would use, or None if the case has never been approved.

    Runs use this rather than the newest version, so that writing a draft for
    the next round does not change what the current round is measuring.
    """
    approved = [v for v in case.versions if v.is_approved]
    return approved[-1] if approved else None
