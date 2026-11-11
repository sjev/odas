#!/usr/bin/env python3
"""Log-entry step of the 3.0 migration: add the ordering letter, fix legacy field names.

Called by migrate_to_types.py; runnable on its own for a re-check. Idempotent.

1. `JJJJ-MM-DD-{IN|UIT|LOG}-slug` -> `JJJJ-MM-DD-A-{IN|UIT|LOG}-slug`. Letters are
   handed out per date in current mtime order -- the last moment mtime is worth
   trusting, since it is exactly what the old reader sorted on. Entries that already
   carry a letter keep it. Files and folders are renamed alike.
2. Legacy entry frontmatter: `omschrijving` -> `onderwerp`, `naar` -> `aan`, and a
   `datum:` that merely repeats the name-date is dropped. `van` and `bron` are left
   alone -- they survive as unknown keys, and dropping a user's data is not our call.
"""

import re
import string
import sys
from pathlib import Path

DIRECTIONS = ("IN", "UIT", "LOG")
KEY_RENAMES = {"omschrijving": "onderwerp", "naar": "aan"}


def parse(stem: str) -> tuple[str, str, str] | None:
    """(datum, letter, rest) for a log-entry stem; letter "" when it has none."""
    parts = stem.split("-")
    if len(parts) > 5 and len(parts[3]) == 1 and parts[3] in string.ascii_uppercase:
        return "-".join(parts[:3]), parts[3], "-".join(parts[4:])
    if len(parts) > 4 and parts[3] in DIRECTIONS:
        return "-".join(parts[:3]), "", "-".join(parts[3:])
    return None


def _fix_frontmatter(path: Path, datum: str, dry_run: bool) -> int:
    """Rename legacy keys and drop a redundant `datum:`. 1 when it changed."""
    text = path.read_text(encoding="utf8")
    updated = text
    for old, new in KEY_RENAMES.items():
        updated = re.sub(rf"^{old}:", f"{new}:", updated, count=1, flags=re.MULTILINE)
    updated = re.sub(rf"^datum:\s*{re.escape(datum)}\s*$\n", "", updated, flags=re.MULTILINE)
    if updated == text:
        return 0
    if dry_run:
        print(f"  [dry] fields {path.parent.name}/{path.name}")
    else:
        path.write_text(updated, encoding="utf8")
        print(f"  fields {path.parent.name}/{path.name}")
    return 1


def _rename(entry: Path, datum: str, letter: str, rest: str, dry_run: bool) -> int:
    """Rename one entry (file or folder) to carry `letter`. 1 when it acted."""
    suffix = ".md" if entry.is_file() else ""
    target = entry.with_name(f"{datum}-{letter}-{rest}{suffix}")
    if target.exists():
        print(f"  SKIP {entry.name}: {target.name} already exists")
        return 0
    if dry_run:
        print(f"  [dry] rename {entry.name} -> {target.name}")
    else:
        entry.rename(target)
        print(f"  renamed {entry.name} -> {target.name}")
    return 1


def migrate_log(zaak_folder: Path, dry_run: bool = True) -> int:
    """Letter and clean every entry in one zaak's log/. Returns the action count."""
    log_dir = zaak_folder / "log"
    if not log_dir.is_dir():
        return 0

    parsed: list[tuple[Path, str, str, str]] = []  # entry, datum, letter, rest
    used: dict[str, set[str]] = {}
    for p in sorted(log_dir.iterdir()):
        stem = p.name[:-3] if p.is_file() and p.suffix == ".md" else p.name
        got = parse(stem)
        if got is None:
            print(f"  SKIP {p.name}: name breaks the grammar")
            continue
        datum, letter, rest = got
        parsed.append((p, datum, letter, rest))
        if letter:
            used.setdefault(datum, set()).add(letter)

    actions = 0
    for entry, datum, letter, rest in sorted(
        parsed, key=lambda t: (t[0].stat().st_mtime, t[0].name)
    ):
        text_file = entry if entry.is_file() else entry / "index.md"
        if text_file.is_file():
            actions += _fix_frontmatter(text_file, datum, dry_run)
        if letter:
            continue
        taken = used.setdefault(datum, set())
        letter = next((c for c in string.ascii_uppercase if c not in taken), "Z")
        taken.add(letter)
        actions += _rename(entry, datum, letter, rest, dry_run)
    return actions


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    zaken = Path(args[0] if args else "data") / "zaken"
    if not zaken.is_dir():
        sys.exit(f"{zaken} not found — run from the project root or pass a data dir.")
    print("Dry run — pass --apply to write.\n" if dry_run else "Applying migration.\n")
    total = sum(migrate_log(f, dry_run) for f in sorted(zaken.iterdir()) if f.is_dir())
    print(f"\n{total} action{'' if total == 1 else 's'}{' would be' if dry_run else ''} applied.")
