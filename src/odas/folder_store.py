"""Folder-scan helpers over a store of records.

A record is a `{prefix}NNNNN-slug` folder under a root dir, with an index.md
holding YAML frontmatter. This module finds and lists them; reading one whole
(audit history, log entries) stays in `zaak.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from hmac import compare_digest
from pathlib import Path
from typing import TypeVar

import yaml

T = TypeVar("T")

# A capability is not case information, so it sits beside the record rather than
# inside it: `cat index.md`, an export and an AI briefing all stay clean.
TOKEN_FILE = ".access-token"
TOKEN_MODE = 0o600


def ref_from_folder(folder: Path) -> str:
    """Strip the slug: zk-34765-x -> zk-34765, ds-2041-x -> ds-2041."""
    return "-".join(folder.name.split("-", 2)[:2])


def find(root: Path, entity_id: str) -> Path | None:
    """Prefix-route a reference number (e.g. zk-NNNNN) to its folder under root."""
    if not root.is_dir():
        return None
    for p in root.iterdir():
        if p.is_dir() and (p.name == entity_id or p.name.startswith(f"{entity_id}-")):
            return p
    return None


def read_token(folder: Path) -> str:
    """This record's capability token, or "" for a record that carries none."""
    path = folder / TOKEN_FILE
    return path.read_text(encoding="utf8").strip() if path.is_file() else ""


def write_token(folder: Path, token: str) -> None:
    """Mint the capability into its own file, readable by the owner only."""
    path = folder / TOKEN_FILE
    path.write_text(f"{token}\n", encoding="utf8")
    path.chmod(TOKEN_MODE)


def find_by_token(root: Path, token: str) -> Path | None:
    """Find a folder by its capability token. Empty token never matches."""
    if not token or not root.is_dir():
        return None
    for p in root.iterdir():
        if p.is_dir() and (held := read_token(p)) and compare_digest(held, token):
            return p
    return None


def list_folders(root: Path, prefix: str = "") -> list[Path]:
    """The record folders under root, name-sorted; `prefix` narrows to one ref prefix.

    One scan answers a whole listing. A caller that has the folder never asks
    `find()` for it again.
    """
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith(prefix))


def list_ids(root: Path, prefix: str = "") -> list[str]:
    """Folder names under root, sorted; `prefix` narrows to one ref prefix."""
    return [p.name for p in list_folders(root, prefix)]


def load_safe(
    folder: Path,
    load: Callable[[Path], T],
    make_error: Callable[[str, str, str, str], T],
) -> T:
    """Like load(folder), but never raises: parse/OS errors produce an error record.

    `make_error(id, ref, body, message)` builds the entity's error record.
    """
    try:
        return load(folder)
    except (yaml.YAMLError, OSError) as e:
        index = folder / "index.md"
        body = index.read_text(encoding="utf8", errors="replace") if index.is_file() else ""
        return make_error(folder.name, ref_from_folder(folder), body, str(e))


def parse_created(ts: str | None) -> datetime | None:
    """Parse an ISO timestamp field ('aangemaakt', 'gewijzigd'); None if missing/malformed."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None
