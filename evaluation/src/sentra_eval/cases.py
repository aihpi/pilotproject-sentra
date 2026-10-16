"""Reading and writing test cases.

Everything that enforces the immutability rules is here rather than in the
router, because the YAML import in the next task is a second writer and a guard
that lives in a request handler would not apply to it.
"""

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from sentra_eval import labels
from sentra_eval.bestand import Bestand
from sentra_eval.models import ENTWURF, FREIGEGEBEN, Case, CaseVersion, Counter

# The counter behind every case number. Tag prefixes are counters too, named
# after the prefix, and none of them can be called this.
NUMMER_COUNTER = "nummer"

# A generated tag: a prefix, then its running number, "FI-007".
GENERATED_TAG = re.compile(r"(?P<prefix>.+)-(?P<number>\d{3,})")


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
    """No case with that number."""


class TagTaken(CaseError):
    """Another case already carries this tag."""


# ── Numbers and tags ────────────────────────────────────────────────


def _counter(session: Session, name: str) -> Counter:
    """The counter row, locked for the rest of the transaction.

    Locked so two imports running at once cannot both read the same
    next_number. Without the lock this is the classic read-modify-write race,
    and the symptom would be a unique-constraint error that looks like a bug in
    the caller.
    """
    row = session.execute(
        select(Counter).where(Counter.name == name).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = Counter(name=name, next_number=1)
        session.add(row)
        session.flush()
    return row


def _take(session: Session, name: str) -> int:
    row = _counter(session, name)
    number = row.next_number
    row.next_number = number + 1
    session.flush()
    return number


def _reserve(session: Session, name: str, number: int) -> None:
    """Make sure the counter never hands out `number` or anything below it."""
    row = _counter(session, name)
    row.next_number = max(row.next_number, number + 1)
    session.flush()


def allocate_nummer(session: Session) -> int:
    """The next case number. Never returns the same one twice.

    A counter rather than max(nummer) + 1, which would hand the number back the
    moment the highest case is withdrawn.
    """
    return _take(session, NUMMER_COUNTER)


def generate_tag(session: Session, prefix: str) -> str:
    """The next free tag with this prefix, skipping any set by hand."""
    while True:
        tag = f"{prefix}-{_take(session, prefix):03d}"
        if not _tag_in_use(session, tag):
            return tag


def _tag_in_use(session: Session, tag: str, *, apart_from: Case | None = None) -> bool:
    statement = select(Case.id).where(Case.tag == tag)
    if apart_from is not None:
        statement = statement.where(Case.id != apart_from.id)
    return session.execute(statement).first() is not None


def set_tag(session: Session, case: Case, tag: str) -> Case:
    """Give a case a tag by hand. It is kept from then on, whatever its labels.

    An empty tag hands the case back to the generator.
    """
    tag = tag.strip()
    if not tag:
        case.tag = generate_tag(session, labels.tag_prefix(case.kategorie, case.testart))
        case.tag_manuell = False
        session.flush()
        return case
    if _tag_in_use(session, tag, apart_from=case):
        raise TagTaken(f"Der Tag {tag!r} ist schon vergeben.")
    case.tag = tag
    case.tag_manuell = True
    session.flush()
    return case


# ── Writing ─────────────────────────────────────────────────────────


def create_case(
    session: Session,
    kategorie: str,
    ausgangsfrage: str,
    *,
    testart: str = "",
    frageform: str = "",
    herkunft: str = "manuell",
    abteilung: str = "",
    erwartete_antwort: str = "",
    referenz_korrekt: str = "",
    referenz_falsch: str = "",
    referenz_korrekt_az: str = "",
    referenz_falsch_az: str = "",
    grund_fuer_aufnahme: str = "",
    grenzfall: bool = False,
    feedback_id: str = "",
) -> tuple[Case, CaseVersion]:
    """A new case with its first version, as a draft.

    Always a draft, even when every field is filled in. Approval is a separate
    act with its own timestamp, and collapsing the two would mean the audit
    trail could not distinguish "written and approved together" from "approved
    without anyone reading it".
    """
    kategorie = labels.normalise_kategorie(str(kategorie))
    testart = testart.strip()
    case = Case(
        nummer=allocate_nummer(session),
        tag=generate_tag(session, labels.tag_prefix(kategorie, testart)),
        kategorie=kategorie,
        testart=testart,
        frageform=frageform.strip(),
        herkunft=herkunft.strip(),
    )
    if testart == labels.GRENZFALL_AUSSERHALB:
        grenzfall = True
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
        feedback_id=feedback_id,
    )
    session.add(version)
    session.flush()
    return case, version


def edit_draft(session: Session, version: CaseVersion, **fields: object) -> CaseVersion:
    """Change a draft in place. Refuses an approved version."""
    if version.is_approved:
        raise ApprovedVersionIsImmutable(
            f"Nr. {version.case.nummer} version {version.version} is approved. "
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
        "feedback_id": latest.feedback_id,
    }
    carried.update({k: v for k, v in fields.items() if v is not None})

    version = CaseVersion(case_id=case.id, version=latest.version + 1, status=ENTWURF, **carried)
    session.add(version)
    session.flush()
    return version


def approval_blockers(version: CaseVersion, bestand: Bestand | None = None) -> list[str]:
    """What stands between this version and approval, in words for the screen.

    Without a Bestand the index is not consulted. Only the two ways a person
    approves (the endpoint behind the button, and an imported file) pass one,
    and they always do; the store itself stays free of HTTP.
    """
    blockers = []
    if not version.erwartete_antwort.strip():
        blockers.append("erwartete Antwort fehlt")
    if version.grenzfall:
        return blockers

    if not version.referenz_korrekt.strip():
        blockers.append("Referenzquelle (korrekt) fehlt")
    # Without it 4.3b and the retrieval check can only say "nicht prüfbar" (#257).
    if not version.referenz_korrekt_az.strip():
        blockers.append("Aktenzeichen der korrekten Quelle fehlt")
    elif bestand is not None:
        if not bestand.erreichbar:
            blockers.append(bestand.fehler)
        elif not bestand.enthaelt(version.referenz_korrekt_az):
            blockers.append(
                f"{version.referenz_korrekt_az.strip()} ist nicht im Bestand, bitte erst einlesen"
            )
    return blockers


def approve(
    session: Session, version: CaseVersion, *, bestand: Bestand | None = None
) -> CaseVersion:
    """Turn a draft into a yardstick.

    Refuses anything that could not actually be measured against. An approved
    version with no expected answer would pass every check by having nothing to
    check, which is worse than no case at all.

    A Grenzfall is the exception to the reference requirement, and has to be:
    it is a question the corpus holds no document for, so there is no correct
    source to name. Demanding one would mean inventing a source for a question
    that has none — which 4.3b would then compare against — and would make 4.4
    unreachable, since the runner only plans approved versions. Its yardstick is
    the expected answer plus the flag itself.
    """
    if version.is_approved:
        return version

    blockers = approval_blockers(version, bestand)
    if blockers:
        raise IncompleteCase(
            f"Nr. {version.case.nummer} Version {version.version} kann nicht freigegeben "
            f"werden: {'; '.join(blockers)}."
        )

    version.status = FREIGEGEBEN
    version.freigegeben_at = datetime.now(UTC)
    session.flush()
    return version


def seed_case(
    session: Session,
    *,
    nummer: int,
    tag: str,
    kategorie: str,
    testart: str = "",
    frageform: str = "",
    herkunft: str = "",
    **content: object,
) -> tuple[Case, CaseVersion]:
    """Create a case at a number that was allocated elsewhere.

    For restoring an exported file into an empty database, and for nothing
    else. The counters are advanced past the number and the tag's running
    number, so neither can be handed out again; without that, seeding Nr. 7 and
    then creating a case normally would produce a second Nr. 7, which is the
    exact failure the counter exists to prevent.

    Deliberately not reachable from the API. The import CLI asks for it with an
    explicit flag, so it cannot happen as a side effect of a normal import.
    """
    if nummer < 1:
        raise CaseError(f"{nummer} is not a case number.")
    kategorie = labels.normalise_kategorie(str(kategorie))
    tag = tag.strip() or f"{labels.tag_prefix(kategorie, testart)}-{nummer:03d}"
    if _tag_in_use(session, tag):
        raise TagTaken(f"Der Tag {tag!r} ist schon vergeben.")

    case = Case(
        nummer=nummer,
        tag=tag,
        kategorie=kategorie,
        testart=testart,
        frageform=frageform,
        herkunft=herkunft,
    )
    session.add(case)
    session.flush()

    _reserve(session, NUMMER_COUNTER, nummer)
    generated = GENERATED_TAG.fullmatch(tag)
    if generated is not None:
        _reserve(session, generated.group("prefix"), int(generated.group("number")))

    version = CaseVersion(case_id=case.id, version=1, status=ENTWURF, **content)
    session.add(version)
    session.flush()
    return case, version


def set_labels(
    session: Session,
    case: Case,
    *,
    kategorie: str | None = None,
    testart: str | None = None,
    frageform: str | None = None,
    herkunft: str | None = None,
) -> Case:
    """Correct a case's labels. Creates no version: labels are not what is measured.

    A generated tag follows a new Bereich or Testart; one set by hand stays.
    Choosing or leaving the Testart "Grenzfall · außerhalb des Bestands" sets
    the grenzfall flag on a draft to match. An approved version keeps its flag:
    it is what a round measured against.
    """
    before = (case.kategorie, case.testart)
    if kategorie is not None:
        case.kategorie = labels.normalise_kategorie(kategorie)
    if testart is not None:
        case.testart = testart.strip()
    if frageform is not None:
        case.frageform = frageform.strip()
    if herkunft is not None:
        case.herkunft = herkunft.strip()

    if (case.kategorie, case.testart) != before and not case.tag_manuell:
        case.tag = generate_tag(session, labels.tag_prefix(case.kategorie, case.testart))

    latest = case.versions[-1] if case.versions else None
    if testart is not None and latest is not None and not latest.is_approved:
        if case.testart == labels.GRENZFALL_AUSSERHALB:
            latest.grenzfall = True
        elif before[1] == labels.GRENZFALL_AUSSERHALB:
            latest.grenzfall = False

    session.flush()
    return case


def withdraw(session: Session, case: Case) -> Case:
    """Take a case out of future rounds without freeing its number."""
    if case.zurueckgezogen_at is None:
        case.zurueckgezogen_at = datetime.now(UTC)
        session.flush()
    return case


# ── Reading ─────────────────────────────────────────────────────────


def list_cases(session: Session, *, include_withdrawn: bool = False) -> list[Case]:
    statement = select(Case).options(selectinload(Case.versions)).order_by(Case.nummer)
    if not include_withdrawn:
        statement = statement.where(Case.zurueckgezogen_at.is_(None))
    return list(session.execute(statement).scalars())


def get_case(session: Session, nummer: int) -> Case:
    case = session.execute(
        select(Case).options(selectinload(Case.versions)).where(Case.nummer == nummer)
    ).scalar_one_or_none()
    if case is None:
        raise UnknownCase(f"Kein Testfall mit Nr. {nummer}.")
    return case


def latest_approved(case: Case) -> CaseVersion | None:
    """The version a run would use, or None if the case has never been approved.

    Runs use this rather than the newest version, so that writing a draft for
    the next round does not change what the current round is measuring.
    """
    approved = [v for v in case.versions if v.is_approved]
    return approved[-1] if approved else None


def from_feedback(session: Session, feedback_id: str) -> Case | None:
    """The case already drafted from this feedback entry, if there is one."""
    return (
        session.execute(
            select(Case)
            .join(CaseVersion, CaseVersion.case_id == Case.id)
            .where(CaseVersion.feedback_id == feedback_id)
        )
        .scalars()
        .first()
    )
