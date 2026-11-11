"""Layout 9 → 10: every record carries the moment it last changed.

`gewijzigd:` sits beside `aangemaakt:` in `index.md`. The app sets it with each
audit line, so the overview can put the most recently changed zaak on top.

This script fills it in for the records written before: the time of the last
audit line, else `aangemaakt`. A record with neither gets no stamp and sorts last.
`prullenbak/` is migrated too.

Stdlib only, so a migration keeps running against a data dir the app cannot load.
Dry run by default; pass `apply` to write. Idempotent: a second run reports zero
actions.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^version:\s*9\b", re.MULTILINE)
STORES = ("zaken", "prullenbak")
HINT = "ISO tijdstip, bij elke wijziging"  # as the app writes it: the next save changes nothing
TRAIL_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) \[", re.MULTILINE)
CREATED = re.compile(r'^aangemaakt:[ \t]*"?([^"\s#]+)"?.*\n', re.MULTILINE)
STAMPED = re.compile(r"^gewijzigd:", re.MULTILINE)


def folders(data_dir: Path) -> list[Path]:
    """Every record folder that holds an index.md, in both stores."""
    return sorted(
        p
        for store in STORES
        if (data_dir / store).is_dir()
        for p in (data_dir / store).iterdir()
        if p.is_dir() and (p / "index.md").is_file()
    )


def last_change(folder: Path, head: str) -> str:
    """The time of the last audit line, else the date of intake, else ""."""
    audit = folder / "audit.log"
    trail = TRAIL_LINE.findall(audit.read_text(encoding="utf8")) if audit.is_file() else []
    if trail:
        day, minute = trail[-1]
        return f"{day}T{minute}:00"
    created = CREATED.search(head)
    return created.group(1) if created else ""


def stamp_record(folder: Path, apply: bool) -> int:
    """Put `gewijzigd:` right after `aangemaakt:`, where the next save puts it anyway."""
    index = folder / "index.md"
    text = index.read_text(encoding="utf8")
    head, fence, rest = text.partition("\n---")
    if not text.startswith("---") or not fence or STAMPED.search(head):
        return 0
    head += "\n"  # the fence's own newline, back on the last frontmatter line
    when = last_change(folder, head)
    if not when:
        return 0

    created = CREATED.search(head)
    at = created.end() if created else len(head)
    new = f'{head[:at]}gewijzigd: "{when}" # {HINT}\n{head[at:]}---{rest}'
    if apply:
        index.write_text(new, encoding="utf8")
        print(f"  stamp {index}")
    else:
        print(f"  [dry] stamp {index}")
    return 1


def stamp(config: Path, apply: bool) -> int:
    text = config.read_text(encoding="utf8")
    new = VERSION_RE.sub("version: 10", text)
    if new == text:
        return 0
    if apply:
        config.write_text(new, encoding="utf8")
        print(f"  version 10 {config}")
    else:
        print(f"  [dry] version 10 {config}")
    return 1


def main(data_dir: Path, apply: bool) -> int:
    config = data_dir / ".app" / "config.yaml"
    if not config.is_file():
        sys.exit(f"ERROR: {config} not found. Is {data_dir} an ODAS data dir?")

    found = folders(data_dir)
    print(f"Data dir: {data_dir}  ({len(found)} record folders)\n")
    changed = stamp(config, apply) + sum(stamp_record(f, apply) for f in found)

    print(f"\n{changed} file(s) {'changed' if apply else 'to change'}.")
    if not apply and changed:
        print("Dry run — pass --apply to write.")
    return changed
