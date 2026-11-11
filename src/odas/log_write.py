"""Write log/ entries: dated documents in/out or internal notes on a zaak or dossier."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from odas import clock, documents, schema, users, zaak
from odas.index_write import parse_raw, set_flag
from odas.naming import _parse_date, _safe_filename, next_letter, slugify, write_text_atomic

log = logging.getLogger(__name__)


def _letters_on(log_dir: Path, name_date: str) -> set[str]:
    """Ordering letters already used on `name_date`, so the next entry gets a free one."""
    taken = set()
    for p in log_dir.iterdir():
        stem = p.name[:-3] if p.is_file() and p.suffix == ".md" else p.name
        parsed = zaak.parse_entry_name(stem)
        if parsed and parsed[0] == name_date and parsed[1]:
            taken.add(parsed[1])
    return taken


def _author(by: str) -> str:
    """The writer as a sender: `Naam <adres>`, or nothing when they are not a person.

    A word like `systeem` or `api` is no address, so it stays off a key that holds
    one. The name is taken here, at the write, because the directory can be down
    when the entry is read back.
    """
    if "@" not in by:
        return ""
    name = users.display_name(by)
    return f"{name} <{by}>" if name != by else by


def _write_log_dir(
    folder: Path,
    name_date: str,
    direction: str,
    slug: str,
    fm: dict[str, str],
    body: str,
    attachments: list[tuple[str, bytes]] | None,
    by: str = "",
    at: datetime | None = None,
) -> Path:
    """Write a dated log entry; flat .md without attachments, dir+index.md with.

    `at` is the moment it happened: a message brings its own, a typed entry is now.
    """
    # A message brings its own sender; an entry a person types has none, so the
    # person who typed it is the sender.
    if "van" in schema.log_fields() and not fm.get("van"):
        fm = {**fm, "van": _author(by)}
    fm = {**fm, "aangemaakt": clock.stamp(at)}
    log_dir = folder / "log"
    log_dir.mkdir(exist_ok=True)
    letter = next_letter(_letters_on(log_dir, name_date))
    base = f"{name_date}-{letter}-{direction}-{slug or 'entry'}"
    name = base
    i = 2
    while (log_dir / f"{name}.md").exists() or (log_dir / name).exists():
        name = f"{base}-{i}"
        i += 1

    text = schema.dump(fm, body, schema.log_fields())
    if not attachments:
        entry = log_dir / f"{name}.md"
        write_text_atomic(entry, text)
        return entry

    entry = log_dir / name
    entry.mkdir()
    write_text_atomic(entry / "index.md", text)
    taken: set[str] = {"index.md"}
    for fname, content in attachments:
        (entry / _safe_filename(fname, taken)).write_bytes(content)
    documents.extract_dir(entry)
    return entry


def _flag(folder: Path, direction: str, by: str) -> None:
    """A message that came in needs the team, whatever came before it."""
    if direction == "IN":
        set_flag(folder, True, by)


def write_log_entry(
    folder: Path,
    direction: str,
    onderwerp: str,
    body: str,
    aan: str = "",
    attachments: list[tuple[str, bytes]] | None = None,
    by: str = "systeem",
    datum: str | None = None,
) -> Path:
    """Write a log/ entry from explicit fields (used by intake's indiening entry).

    `datum` (JJJJ-MM-DD) sets the entry date; defaults to today when omitted.
    """
    # A data dir that never sends mail declares no `aan`, so writing one would put
    # a key on disk that its own schema calls unknown.
    declared = schema.log_fields()
    fm = {k: v for k, v in (("onderwerp", onderwerp), ("aan", aan)) if k in declared}
    name_date = _parse_date(datum or "")
    entry = _write_log_dir(
        folder, name_date, direction, slugify(onderwerp), fm, body, attachments, by
    )
    _flag(folder, direction, by)
    log.info(f"Log entry added: ref={folder.name!r} direction={direction!r} by={by!r}")
    return entry


def create_log_entry(
    folder: Path,
    direction: str,
    datum: str,
    raw_text: str,
    attachments: list[tuple[str, bytes]] | None = None,
    by: str = "unknown",
    at: datetime | None = None,
) -> Path:
    """Write a log/ entry from a raw frontmatter+body editor (inline add form).

    Date and direction live in the name, so both come in as separate controls.
    Validates against `schema.log_fields()`, derives the slug from `onderwerp`. Raises
    `ValueError` (Dutch) on bad input.
    """
    if direction not in zaak.DIRECTIONS:
        raise ValueError(f"Ongeldige richting: {direction}.")
    name_date = _parse_date(datum)
    fm, body = parse_raw(raw_text)
    schema.validate(fm, schema.log_fields())
    slug = slugify(fm.get("onderwerp", ""))
    entry = _write_log_dir(folder, name_date, direction, slug, fm, body, attachments, by, at)
    _flag(folder, direction, by)
    log.info(f"Log entry added: ref={folder.name!r} direction={direction!r} by={by!r}")
    return entry


def entry_path(folder: Path, name: str) -> Path | None:
    """Resolve an entry name to the file or folder that *is* the entry. None if unsafe.

    The name is the stem: a flat entry is the file `<stem>.md`, one with attachments
    is the folder `<stem>/`. A caller that moves an entry whole wants this; one that
    reads its text wants `_entry_index_path`.
    """
    if "/" in name or ".." in name or name.startswith("."):
        return None
    flat = folder / "log" / f"{name}.md"
    if flat.is_file():
        return flat
    entry_dir = folder / "log" / name
    return entry_dir if (entry_dir / "index.md").is_file() else None


def _entry_index_path(folder: Path, name: str) -> Path | None:
    """Resolve an entry name to the file holding its text. None if missing/unsafe.

    Which shape the entry has today is not the caller's business — that is what lets
    `update_log_entry` promote one into the other.
    """
    entry = entry_path(folder, name)
    if entry is None:
        return None
    return entry if entry.is_file() else entry / "index.md"


def read_log_entry_raw(folder: Path, name: str) -> str | None:
    """Raw index.md text of one log entry, for the editor. None if not found."""
    index = _entry_index_path(folder, name)
    return index.read_text(encoding="utf8") if index else None


def update_log_entry(
    folder: Path,
    name: str,
    raw_text: str,
    attachments: list[tuple[str, bytes]] | None = None,
    remove: list[str] | None = None,
    direction: str = "",
) -> None:
    """Re-write an existing log entry's text and optionally add/remove attachments.

    A flat entry is promoted to a folder on its first attachment; the entry name and
    so its URL do not change. A new direction does rename it: the direction is a
    segment of the name.
    """
    index = _entry_index_path(folder, name)
    if index is None:
        raise FileNotFoundError(name)
    if direction and direction not in zaak.DIRECTIONS:
        raise ValueError(f"Ongeldige richting: {direction}.")
    fm, body = parse_raw(raw_text)
    schema.validate(fm, schema.log_fields())
    if attachments:
        index = _promote(index)
    write_text_atomic(index, schema.dump(fm, body, schema.log_fields()))

    entry_dir = index.parent
    if entry_dir.name == "log":  # still flat: nothing to remove, nothing was added
        _redirect(index, direction)
        return
    for fname in remove or []:
        target = entry_dir / Path(fname).name
        if target.name != "index.md" and target.is_file():
            target.unlink()
    if attachments:
        taken = {p.name for p in entry_dir.iterdir()}
        for fname, content in attachments:
            (entry_dir / _safe_filename(fname, taken)).write_bytes(content)
        documents.extract_dir(entry_dir)
    _redirect(entry_dir, direction)


def _redirect(entry: Path, direction: str) -> None:
    """Rename a flat file or a folder to carry `direction`; a blank one leaves it be."""
    stem = entry.name.removesuffix(".md")
    parsed = zaak.parse_entry_name(stem)
    if not direction or parsed is None or parsed[2] == direction:
        return
    new_stem = stem.replace(f"-{parsed[2]}-", f"-{direction}-", 1)  # the date holds no letters
    entry.rename(entry.with_name(new_stem + entry.name.removeprefix(stem)))


def _promote(index: Path) -> Path:
    """Turn a flat `<stem>.md` entry into `<stem>/index.md`. No-op if already a folder."""
    if index.name == "index.md":
        return index
    entry_dir = index.with_suffix("")
    entry_dir.mkdir()
    target = entry_dir / "index.md"
    os.replace(index, target)
    return target
