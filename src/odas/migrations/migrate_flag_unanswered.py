"""Layout 12 → 13: a zaak carries its own flag.

`opvolgen: ja` in `index.md` marks a zaak that waits for the team. Before, the app
derived the mark: the newest log entry was an `IN`. An IN now sets the flag and
only a person clears it.

This script sets the flag where the old rule showed the mark, so no zaak loses
it on the deploy. `prullenbak/` is migrated too. It writes the key `opvolgen`;
the config declares it, as `opvolgen: {type: flag}`, on each type that has one.

Stdlib only, so a migration keeps running against a data dir the app cannot load.
Dry run by default; pass `apply` to write. Idempotent: a second run reports zero
actions.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^version:\s*12\b", re.MULTILINE)
STORES = ("zaken", "prullenbak")
# JJJJ-MM-DD-A-IN-slug; a legacy name has no letter, and sorts before a lettered one.
ENTRY = re.compile(r"^(\d{4}-\d{2}-\d{2})-(?:([A-Za-z])-)?(IN|UIT|LOG)-")
FLAGGED = re.compile(r"^opvolgen:", re.MULTILINE)


def folders(data_dir: Path) -> list[Path]:
    """Every record folder that holds an index.md, in both stores."""
    return sorted(
        p
        for store in STORES
        if (data_dir / store).is_dir()
        for p in (data_dir / store).iterdir()
        if p.is_dir() and (p / "index.md").is_file()
    )


def came_in_last(folder: Path) -> bool:
    """The old rule: the newest entry, by date then letter, is an IN."""
    log = folder / "log"
    found = [ENTRY.match(p.name) for p in log.iterdir()] if log.is_dir() else []
    entries = sorted((m.group(1), (m.group(2) or "").upper(), m.group(3)) for m in found if m)
    return bool(entries) and entries[-1][2] == "IN"


def flag_record(folder: Path, apply: bool) -> int:
    """Put `opvolgen: ja` last in the frontmatter; the next save puts it in its place."""
    index = folder / "index.md"
    text = index.read_text(encoding="utf8")
    head, fence, rest = text.partition("\n---")
    if not text.startswith("---") or not fence or FLAGGED.search(head) or not came_in_last(folder):
        return 0
    new = f"{head}\nopvolgen: ja\n---{rest}"
    if apply:
        index.write_text(new, encoding="utf8")
        print(f"  flag {index}")
    else:
        print(f"  [dry] flag {index}")
    return 1


def stamp(config: Path, apply: bool) -> int:
    text = config.read_text(encoding="utf8")
    new = VERSION_RE.sub("version: 13", text)
    if new == text:
        return 0
    if apply:
        config.write_text(new, encoding="utf8")
        print(f"  version 13 {config}")
    else:
        print(f"  [dry] version 13 {config}")
    return 1


def main(data_dir: Path, apply: bool) -> int:
    config = data_dir / ".app" / "config.yaml"
    if not config.is_file():
        sys.exit(f"ERROR: {config} not found. Is {data_dir} an ODAS data dir?")

    found = folders(data_dir)
    print(f"Data dir: {data_dir}  ({len(found)} record folders)\n")
    changed = stamp(config, apply) + sum(flag_record(f, apply) for f in found)

    print(f"\n{changed} file(s) {'changed' if apply else 'to change'}.")
    if not apply and changed:
        print("Dry run — pass --apply to write.")
    return changed
