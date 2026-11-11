#!/usr/bin/env python3
"""One-time migration to the type registry: stamp `soort:`/`titel:`, fold dossiers into zaken.

Three actions, all idempotent -- each guards on the value it writes, so a second
run reports zero actions:

1. every `data/zaken/*/index.md` without a `soort:` line gets `soort: hulpvraag`,
   and an empty `titel:` is backfilled from the folder slug;
2. every `data/dossiers/ds-*` moves into `data/zaken/` (a rename on the same
   filesystem, so audit.log, log/ and attachments come along) and is stamped
   `soort: dossier`;
3. every log entry gains its ordering letter and its legacy field names are
   fixed -- see migrate_log_entries.py;
4. `.app/app-version` is stamped with the app major this layout belongs to --
   the app refuses to start against data whose major differs.

Listing is prefix-agnostic now: every subdir of `zaken/` is a record. Any subdir
without an index.md is therefore a broken record and is reported. `zaken/old/`
(the pre-`zk-` archive) is one such; `--drop-old` deletes it. That flag is opt-in
because this script also runs against production, where the delete is final.

`ds-` refs are kept as they are: they are referenced from sent mail and from the
dossier's own frontmatter. Dry run by default; pass --apply to write.
"""

import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from migrate_log_entries import migrate_log

BASE_ORDER = ("id", "soort", "titel", "aangemaakt")
TARGET_VERSION = "3.0.0"  # this layout is served by odas 3.x


def _folder_title(folder_name: str) -> str:
    """`zk-00001-mestverwerking-grubbenvorst` -> `Mestverwerking grubbenvorst`."""
    slug = re.sub(r"^[a-z]{2,3}-\d+-?", "", folder_name)
    text = slug.replace("-", " ").strip()
    return text[:1].upper() + text[1:]


def _read_value(text: str, key: str) -> str | None:
    """The frontmatter value for `key`, or None when the key is absent."""
    match = re.search(rf"^{key}:(.*)$", text, flags=re.MULTILINE)
    if match is None:
        return None
    return match.group(1).split("#")[0].strip().strip("\"'")


def _set_value(text: str, key: str, value: str) -> str:
    """Set (or insert) `key: value`, keeping the base keys in their canonical order."""
    if _read_value(text, key) is not None:
        return re.sub(rf"^{key}:.*$", f"{key}: {value}", text, count=1, flags=re.MULTILINE)
    lines = text.splitlines()
    after = BASE_ORDER[: BASE_ORDER.index(key)]
    insert_at = 1  # directly under the opening ---
    for i, line in enumerate(lines):
        if any(line.startswith(f"{k}:") for k in after):
            insert_at = i + 1
    lines.insert(insert_at, f"{key}: {value}")
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _stamp(index: Path, soort: str, dry_run: bool) -> bool:
    """Give index.md a `soort:` and a non-empty `titel:`. True when it changed."""
    text = index.read_text(encoding="utf8")
    updated = text
    if _read_value(text, "soort") is None:
        updated = _set_value(updated, "soort", soort)
    if not _read_value(updated, "titel"):
        updated = _set_value(updated, "titel", _folder_title(index.parent.name))
    if updated == text:
        return False
    if dry_run:
        print(f"  [dry] stamp {index.parent.name}: soort={soort}")
    else:
        index.write_text(updated, encoding="utf8")
        print(f"  stamped {index.parent.name}: soort={soort}")
    return True


def _drop_old(folder: Path, dry_run: bool) -> int:
    """Delete `zaken/old/`, the archive of pre-`zk-` folders. 1 when it acted."""
    count = sum(1 for _ in folder.iterdir())
    if dry_run:
        print(f"  [dry] delete {folder.parent.name}/{folder.name}/ ({count} folders)")
    else:
        shutil.rmtree(folder)
        print(f"  deleted {folder.parent.name}/{folder.name}/")
    return 1


def _stamp_version(data_dir: Path, dry_run: bool) -> int:
    """Record the app major this layout belongs to; the app refuses mismatched data."""
    path = data_dir / ".app" / "app-version"
    if path.is_file() and path.read_text(encoding="utf8").strip() == TARGET_VERSION:
        return 0
    if dry_run:
        print(f"  [dry] stamp .app/app-version = {TARGET_VERSION}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{TARGET_VERSION}\n", encoding="utf8")
        print(f"  stamped .app/app-version = {TARGET_VERSION}")
    return 1


def migrate(data_dir: Path, dry_run: bool = True, drop_old: bool = False) -> int:
    zaken_dir, dossiers_dir = data_dir / "zaken", data_dir / "dossiers"
    actions = 0

    for folder in sorted(p for p in zaken_dir.iterdir() if p.is_dir()):
        if (folder / "index.md").is_file():
            actions += _stamp(folder / "index.md", "hulpvraag", dry_run)
        elif folder.name == "old" and drop_old:
            actions += _drop_old(folder, dry_run)
        elif folder.name == "old":
            print(f"  SKIP {folder.name}: pass --drop-old to delete")
        else:
            print(f"  SKIP {folder.name}: no index.md — not a record, move or delete it")

    for folder in sorted(dossiers_dir.glob("ds-*")) if dossiers_dir.is_dir() else []:
        target = zaken_dir / folder.name
        if target.exists():
            print(f"  SKIP {folder.name}: {target} already exists")
            continue
        if dry_run:
            print(f"  [dry] move {folder} -> {target}")
            actions += 1
            continue
        folder.rename(target)
        print(f"  moved {folder.name} -> zaken/")
        actions += 1
        _stamp(target / "index.md", "dossier", dry_run=False)

    # After the move, so folded-in dossiers get their log entries lettered too.
    for folder in sorted(p for p in zaken_dir.iterdir() if p.is_dir()):
        actions += migrate_log(folder, dry_run)

    actions += _stamp_version(data_dir, dry_run)
    return actions


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    drop_old = "--drop-old" in sys.argv
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
    data_dir = data_dir or Path("data")
    if not (data_dir / "zaken").is_dir():
        sys.exit(f"{data_dir}/zaken not found — run from the project root or pass a data dir.")

    print("Dry run — pass --apply to write.\n" if dry_run else "Applying migration.\n")
    count = migrate(data_dir, dry_run=dry_run, drop_old=drop_old)
    print(f"\n{count} action{'' if count == 1 else 's'}{' would be' if dry_run else ''} applied.")
