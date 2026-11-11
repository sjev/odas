"""One encrypted zip of the whole data dir, made on request from the Extra page.

The password is random and is kept in a text file beside the zip, so the list
can show it again after a reload. Earlier backups and the logs are left out:
a backup is the record, not the record of making records.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pyzipper

from odas.config import Config

SKIPPED = ("backups", "logs")  # under .app/; the rest of the data dir is included
PART = ".part"  # a zip keeps this suffix until it is complete
RUNNING = threading.Lock()  # one backup at a time; the server runs one process


@dataclass(frozen=True)
class Backup:
    name: str  # the zip file name
    password: str
    size: int
    made_at: datetime


def backups_dir() -> Path:
    return Config().data_dir / "backups"


def _skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).parts
    return len(rel) >= 2 and rel[0] == ".app" and rel[1] in SKIPPED


def start() -> bool:
    """Claim the one backup slot. False while a backup runs."""
    return RUNNING.acquire(blocking=False)


def run() -> None:
    """Make a backup in the slot that `start` claimed, and free the slot after."""
    try:
        create()
    finally:
        RUNNING.release()


def create() -> Backup:
    """Zip the data dir under a fresh password; return what the page shows."""
    root = Config().root
    folder = backups_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for left in folder.glob(f"*{PART}"):  # a crash left it; nothing else writes here
        left.unlink()
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    password = secrets.token_urlsafe(18)
    target = folder / f"{stamp}.zip"
    part = target.with_name(target.name + PART)
    with pyzipper.AESZipFile(
        part, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
    ) as zf:
        zf.setpassword(password.encode())
        for path in sorted(root.rglob("*")):
            if path.is_file() and not _skip(path, root):
                zf.write(path, str(path.relative_to(root)))
    (folder / f"{stamp}.txt").write_text(password, encoding="utf8")
    part.rename(target)
    return _read(target)


def _read(zip_path: Path) -> Backup:
    password = zip_path.with_suffix(".txt")
    return Backup(
        name=zip_path.name,
        password=password.read_text(encoding="utf8").strip() if password.exists() else "",
        size=zip_path.stat().st_size,
        made_at=datetime.fromtimestamp(zip_path.stat().st_mtime),
    )


def list_backups() -> list[Backup]:
    """Every backup on disk, newest first."""
    folder = backups_dir()
    if not folder.is_dir():
        return []
    return [_read(p) for p in sorted(folder.glob("*.zip"), reverse=True)]


def find(name: str) -> Path | None:
    """The zip with this exact name, or None. A name is never a path."""
    if name != Path(name).name or not name.endswith(".zip"):
        return None
    path = backups_dir() / name
    return path if path.is_file() else None


def delete(zip_path: Path) -> None:
    """Remove a backup and its password. Real removal: nothing else holds a copy."""
    zip_path.unlink()
    zip_path.with_suffix(".txt").unlink(missing_ok=True)
