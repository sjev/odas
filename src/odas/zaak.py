"""Zaak model: read-only view of index.md, audit.log, and log/ entries."""

from __future__ import annotations

import logging
import string
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from odas import clock, folder_store, schema
from odas.appconfig import default_type_name, type_fields
from odas.config import Config
from odas.fields import (
    FlagField,
    LatLonField,
    StatusField,
    TermijnField,
    ToegangField,
    UserField,
    declared_key,
)

log = logging.getLogger(__name__)

AUDIT_FILE = "audit.log"
# What is inside a document and what was made of it, both stored beside it. Part
# of the case, never a file of it: `index.py` writes these, and the layout keeps
# them out of the list.
TEXT_SUFFIX = ".tekst.md"
SUMMARY_SUFFIX = ".samenvatting.md"
SIDECARS = (TEXT_SUFFIX, SUMMARY_SUFFIX)
DIRECTIONS = ("IN", "UIT", "LOG")
ORDER_LETTERS = string.ascii_uppercase  # A..Z, orders same-day log entries
ENTRY_GRAMMAR = "JJJJ-MM-DD-A-{IN|UIT|LOG}-slug"


@dataclass
class Termijn:
    """A zaak's deadline, read off its TermijnField for the templates."""

    kind: str
    due: str  # ISO date
    days: int | None  # days remaining; None when the date is unset or unparseable


@dataclass
class LogEntry:
    """One log/ entry: a document in/out or an internal note."""

    name: str  # entry identity: the stem, never the .md (JJJJ-MM-DD-A-{IN|UIT|LOG}-slug)
    datum: str  # date from the name (the entry's date), JJJJ-MM-DD
    letter: str  # A..Z, orders same-day entries; "" on a legacy letterless name
    direction: str  # IN | UIT | LOG
    slug: str
    frontmatter: dict[str, str]
    body: str
    attachments: list[str] = field(default_factory=list)  # paths relative to the zaak folder

    @property
    def time(self) -> str:
        """HH:MM on the clock of the org; "" when that falls on another day than the name."""
        at = folder_store.parse_created(self.frontmatter.get("aangemaakt"))
        if at is None:
            return ""
        at = clock.local(at)
        return f"{at:%H:%M}" if at.date().isoformat() == self.datum else ""

    @property
    def edited(self) -> str:
        """When a person last changed it, as the page shows a moment; "" when never."""
        at = folder_store.parse_created(self.frontmatter.get("gewijzigd"))
        return f"{clock.local(at):%Y.%m.%d %H:%M}" if at else ""


@dataclass
class Zaak:
    id: str  # folder name (ref prefix + slug)
    ref: str  # zk-NNNNN human reference
    frontmatter: dict[str, str]
    body: str
    soort: str = ""  # type-registry key; "" resolves to the base fields only
    history: str = ""  # raw text of audit.log (audit, render-only)
    log_entries: list[LogEntry] = field(default_factory=list)
    error: str | None = None  # set by load_safe when the folder could not be parsed
    # Read from `.access-token`, never from the frontmatter. `public_view` drops it.
    token: str = ""  # the capability behind /inzien-<token>; "" for a type without one

    @property
    def fields(self) -> dict[str, schema.Field]:
        """The field declaration of this zaak's soort."""
        return type_fields(self.soort)

    @property
    def titel(self) -> str:
        """Display name. The folder slug is frozen at creation, so this is the rename."""
        return self.frontmatter.get("titel") or self.ref

    def _value_of(self, kind: type[schema.Field]) -> str:
        """This zaak's value for the field of that kind; "" for a type without one.

        `declared_key` returns "", which is never a frontmatter key, so a type
        that declares no field of the kind answers empty rather than raising.
        """
        return self.frontmatter.get(declared_key(self.fields, kind), "")

    @property
    def status(self) -> str | None:
        """Where this zaak stands, whatever its type calls the field; None without one."""
        return self._value_of(StatusField) or None

    @property
    def badge(self) -> tuple[str, str] | None:
        """(label, css) of this zaak's status, or None for a type without one."""
        f = self.fields.get(declared_key(self.fields, StatusField))
        return f.badge(self._value_of(StatusField)) if isinstance(f, StatusField) else None

    @property
    def toegang(self) -> set[str]:
        """Emails granted access to this zaak; empty for a type without a toegang field."""
        f = self.fields.get(declared_key(self.fields, ToegangField))
        return f.emails(self._value_of(ToegangField)) if isinstance(f, ToegangField) else set()

    @property
    def point(self) -> str:
        """This zaak's place as decimal `lat,lon`, whatever its type calls the field; "" without one."""
        f = self.fields.get(declared_key(self.fields, LatLonField))
        return f.point(self._value_of(LatLonField)) if isinstance(f, LatLonField) else ""

    @property
    def behandelaar(self) -> str | None:
        """The internal owner, whatever the type calls the field; None for a type without one."""
        return self._value_of(UserField) or None

    @property
    def _termijn_field(self) -> TermijnField | None:
        return next((f for f in self.fields.values() if isinstance(f, TermijnField)), None)

    @property
    def termijn(self) -> Termijn | None:
        f = self._termijn_field
        if f is None or not f.due(self.frontmatter):
            return None
        return Termijn(
            kind=f.kind(self.frontmatter),
            due=f.due(self.frontmatter),
            days=f.days_remaining(self.frontmatter),
        )

    @property
    def flagged(self) -> bool:
        """The work waits for the team. An IN sets it; only a person clears it."""
        key = declared_key(self.fields, FlagField)
        return bool(key) and self.frontmatter.get(key) == "ja"

    @property
    def created(self) -> datetime | None:
        at = folder_store.parse_created(self.frontmatter.get("aangemaakt"))
        return clock.local(at) if at else None

    @property
    def modified(self) -> datetime | None:
        at = folder_store.parse_created(self.frontmatter.get("gewijzigd"))
        return clock.local(at) if at else None


def parse_entry_name(stem: str) -> tuple[str, str, str, str] | None:
    """Parse JJJJ-MM-DD-A-{IN|UIT|LOG}-slug into (datum, letter, direction, slug).

    A letterless legacy name still parses, with letter "" — a hand-made file must
    never silently vanish from the view. `check_all` reports it instead. A lowercase
    letter is read as its uppercase, for the same reason.
    """
    parts = stem.split("-")
    if len(parts) > 5 and len(parts[3]) == 1 and parts[3].upper() in ORDER_LETTERS:
        letter, direction, rest = parts[3].upper(), parts[4], parts[5:]
    elif len(parts) > 4:
        letter, direction, rest = "", parts[3], parts[4:]
    else:
        return None
    if direction not in DIRECTIONS:
        return None
    return "-".join(parts[0:3]), letter, direction, "-".join(rest)


def _read_entry(
    name: str, parsed: tuple[str, str, str, str], body_file: Path, attachments: list[str]
) -> LogEntry:
    datum, letter, direction, slug = parsed
    fm, body = (
        schema.parse(body_file.read_text(encoding="utf8")) if body_file.is_file() else ({}, "")
    )
    return LogEntry(
        name=name,
        datum=datum,
        letter=letter,
        direction=direction,
        slug=slug,
        frontmatter=fm,
        body=body,
        attachments=sorted(attachments),
    )


def scan_log(folder: Path) -> list[LogEntry]:
    """Walk log/ into chronological LogEntry list. Malformed names are logged and skipped."""
    log_dir = folder / "log"
    if not log_dir.is_dir():
        return []
    entries: list[LogEntry] = []
    for p in sorted(log_dir.iterdir()):
        stem = p.name[:-3] if p.is_file() and p.suffix == ".md" else p.name
        parsed = parse_entry_name(stem)
        if parsed is None:
            log.warning(
                f"Log entry skipped, name breaks the grammar: ref={folder.name!r} entry={p.name!r}"
            )
            continue
        if p.is_dir():
            # Text and summary lie in the entry folder but are never files of the
            # case: not a row in the logboek, not a download, not a name reported.
            attachments = [
                f"log/{p.name}/{f.name}"
                for f in p.iterdir()
                if f.name != "index.md" and not f.name.endswith(SIDECARS)
            ]
            entries.append(_read_entry(stem, parsed, p / "index.md", attachments))
        else:
            entries.append(_read_entry(stem, parsed, p, []))
    # Order is data: it lives in the name. mtime does not survive a copy, rsync or zip.
    return sorted(entries, key=lambda e: (e.datum, e.letter))


def load(folder: Path) -> Zaak:
    """Read one zaak folder into a Zaak (frontmatter = state, events = audit)."""
    index = folder / "index.md"
    text = index.read_text(encoding="utf8") if index.is_file() else ""
    frontmatter, body = schema.parse(text)

    audit = folder / AUDIT_FILE
    history = audit.read_text(encoding="utf8").strip() if audit.is_file() else ""

    ref = frontmatter.get("id") or folder_store.ref_from_folder(folder)
    return Zaak(
        id=folder.name,
        ref=ref,
        frontmatter=frontmatter,
        body=body,
        soort=frontmatter.get("soort") or default_type_name(),
        history=history,
        log_entries=scan_log(folder),
        token=folder_store.read_token(folder),
    )


def _make_error(id_: str, ref: str, body: str, message: str) -> Zaak:
    return Zaak(
        id=id_, ref=ref, frontmatter={}, body=body, error=f"Zaak kan niet worden gelezen: {message}"
    )


def load_safe(folder: Path) -> Zaak:
    """Like load(), but never raises: a malformed zaak comes back with .error set."""
    return folder_store.load_safe(folder, load, _make_error)


@dataclass
class ZaakProblem:
    ref: str  # folder name
    path: str  # file relative to zaken/, e.g. zk-123-x/index.md
    message: str  # Dutch error


def _check_text(text: str, fields: dict[str, schema.Field] | None = None) -> str | None:
    """Parse + validate frontmatter; return a Dutch error message, or None if valid.

    `fields=None` resolves them from the record's own `soort:` -- what an index.md
    is validated against depends on its type. Only then is a key the soort does not
    declare reported: a soort change keeps the key, but drops what it means.
    """
    try:
        fm, _ = schema.parse(text)
    except yaml.YAMLError as e:
        return f"Ongeldige frontmatter: {e}"
    soort = fm.get("soort") or default_type_name() if fields is None else ""
    checked = type_fields(soort) if fields is None else fields
    try:
        schema.validate(fm, checked)
    except ValueError as e:
        return str(e)
    if soort and (extra := schema.undeclared(fm, checked)):
        return f"Soort {soort} kent het veld {', '.join(extra)} niet."
    return None


def check_all() -> list[ZaakProblem]:
    """Scan every zaak folder for parse/schema problems in index.md and log entries."""
    problems: list[ZaakProblem] = []
    for folder in list_folders():
        zid = folder.name
        index = folder / "index.md"
        if not index.is_file():
            problems.append(ZaakProblem(zid, f"{zid}/index.md", "index.md ontbreekt."))
        elif msg := _check_text(index.read_text(encoding="utf8", errors="replace")):
            problems.append(ZaakProblem(zid, f"{zid}/index.md", msg))

        log_dir = folder / "log"
        if not log_dir.is_dir():
            continue
        for p in sorted(log_dir.iterdir()):
            stem = p.name[:-3] if p.is_file() and p.suffix == ".md" else p.name
            parsed = parse_entry_name(stem)
            if parsed is None:
                problems.append(
                    ZaakProblem(
                        zid, f"{zid}/log/{p.name}", f"Naam volgt niet het patroon {ENTRY_GRAMMAR}."
                    )
                )
                continue
            if not parsed[1]:
                problems.append(
                    ZaakProblem(
                        zid,
                        f"{zid}/log/{p.name}",
                        f"Naam mist een volgletter; hernoem naar {ENTRY_GRAMMAR}.",
                    )
                )
            entry = p if p.is_file() else p / "index.md"
            if entry.is_file() and (
                msg := _check_text(
                    entry.read_text(encoding="utf8", errors="replace"), schema.log_fields()
                )
            ):
                problems.append(ZaakProblem(zid, f"{zid}/log/{p.name}", msg))
    return problems


def find(zaak_id: str) -> Path | None:
    """Prefix-route a reference number (zk-NNNNN) to its folder."""
    return folder_store.find(Config().zaken_dir, zaak_id)


def find_by_token(token: str) -> Path | None:
    """Find a zaak folder by its capability token. Empty token never matches."""
    return folder_store.find_by_token(Config().zaken_dir, token)


def list_folders() -> list[Path]:
    """Every record folder under zaken/, name-sorted.

    Prefix-agnostic: a dossier keeps its `ds-` ref after the move into zaken/,
    because that ref is in sent mail.
    """
    return folder_store.list_folders(Config().zaken_dir)


def list_ids() -> list[str]:
    """The name of every record folder under zaken/, in the same order."""
    return [f.name for f in list_folders()]


def list_all() -> list[Zaak]:
    """All zaken, loaded and id-sorted; unreadable ones become an error record."""
    return [load_safe(folder) for folder in list_folders()]


# Jinja filters / globals


def fmt_date(value: Any) -> str:
    """Format an ISO date/datetime (or string) as 'YYYY.MM.DD'."""
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
    if dt.tzinfo is not None:  # a stamp in UTC: the day is the one on the clock of the org
        dt = clock.local(dt)
    return f"{dt.year}.{dt.month:02d}.{dt.day:02d}"
