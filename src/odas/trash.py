"""The prullenbak: where a deleted thing goes.

Delete is a move, never an unlink. A deleted zaak goes to `prullenbak/` beside
`zaken/`; a deleted log entry goes to a `prullenbak/` inside its own zaak, so it
travels with the case if the case goes too. Nothing here removes bytes, and
nothing brings a thing back: a restore is a move on the disk, by a person.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from odas import log_write
from odas.config import Config

log = logging.getLogger(__name__)

TRASH = "prullenbak"


def _free_name(trash_dir: Path, name: str) -> Path:
    """A path in `trash_dir` nothing occupies. The stem gains -2, -3 on collision.

    A deleted entry frees its ordering letter, so the next entry can mint the very
    name that just left. The number keeps both.
    """
    suffix = ".md" if name.endswith(".md") else ""
    stem = name[: -len(suffix)] if suffix else name
    target = trash_dir / name
    i = 2
    while target.exists():
        target = trash_dir / f"{stem}-{i}{suffix}"
        i += 1
    return target


def move(source: Path, trash_dir: Path) -> Path:
    """Move one file or folder into `trash_dir`, keeping its name. Returns where it went."""
    trash_dir.mkdir(parents=True, exist_ok=True)
    target = _free_name(trash_dir, source.name)
    os.replace(source, target)
    return target


def trash_log_entry(folder: Path, name: str) -> Path:
    """Move one log entry into its own zaak's prullenbak. Raises FileNotFoundError."""
    entry = log_write.entry_path(folder, name)
    if entry is None:
        raise FileNotFoundError(name)
    target = move(entry, folder / TRASH)
    log.info(f"Log entry deleted: ref={folder.name!r} entry={name!r}")
    return target


def trash_zaak(folder: Path) -> Path:
    """Move a whole zaak folder, audit trail and all, into the data dir's prullenbak."""
    target = move(folder, Config().prullenbak_dir)
    log.info(f"Zaak deleted: ref={folder.name!r}")
    return target
