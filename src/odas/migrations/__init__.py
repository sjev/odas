"""Bring a data dir up to the layout this app needs.

`STEPS` names the migration that lifts a data dir off one layout. Each step
writes the new `version:` into `config.yaml` itself, so the table and the config
never disagree. Before the first step writes, `backup()` copies every file a
migration can touch into `.backups/<timestamp>/`. That is Markdown, YAML and the
token files only, so the backup stays small.

The app runs this at start (`odas.dataversion.ensure`). `odas upgrade` runs it by
hand, dry by default. Only migrations that still have a volume to run against
live here; a migration every deployment has run is deleted, and git history keeps
it.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from odas.migrations import (
    migrate_columns_to_org,
    migrate_experts_to_toegang,
    migrate_flag_unanswered,
    migrate_mail_capture,
    migrate_stamp_gewijzigd,
    migrate_stamp_log_times,
    migrate_summaries_to_zaak,
    migrate_text_to_zaak,
    migrate_token_to_file,
)

# The migration that lifts a data dir off that layout. Add one line per layout.
STEPS: dict[int, Callable[[Path, bool], object]] = {
    4: migrate_experts_to_toegang.main,
    5: migrate_mail_capture.main,
    6: migrate_summaries_to_zaak.main,
    7: migrate_text_to_zaak.main,
    8: migrate_token_to_file.main,
    9: migrate_stamp_gewijzigd.main,
    10: migrate_columns_to_org.main,
    11: migrate_stamp_log_times.main,
    12: migrate_flag_unanswered.main,
}
# Every migration writes one of these, and nothing else. A document never changes.
BACKUP_PATTERNS = ("*.md", "*.yaml", ".access-token")
BACKUP_DIR = ".backups"
KEEP_DAYS = 30
OLDEST = min(STEPS)


def plan(here: int, there: int) -> list[int]:
    """The layouts to step off, in order. Empty when the data dir is current."""
    if here == there:
        return []
    if here > there:
        raise SystemExit(
            f"This data dir is layout {here} and the app needs {there}. Upgrade the app."
        )
    if here < OLDEST:
        raise SystemExit(
            f"Layout {here} is too old for this app. Take it to layout {OLDEST} by hand "
            f"first: see scripts/README.md."
        )
    return list(range(here, there))


def backup(data_dir: Path) -> Path:
    """Copy every file a migration can write into a new backup folder."""
    into = data_dir / BACKUP_DIR / datetime.now().strftime("%Y-%m-%dT%H%M%S")
    for pattern in BACKUP_PATTERNS:
        for source in data_dir.rglob(pattern):
            if BACKUP_DIR in source.relative_to(data_dir).parts or not source.is_file():
                continue
            copy = into / source.relative_to(data_dir)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copy)
    return into


def prune(data_dir: Path) -> None:
    """A backup holds changed files only, so it stays small. Drop them after a month."""
    limit = time.time() - KEEP_DAYS * 86400
    for old in (data_dir / BACKUP_DIR).iterdir():
        if old.is_dir() and old.stat().st_mtime < limit:
            shutil.rmtree(old)


def run(data_dir: Path, here: int, there: int, apply: bool) -> Path | None:
    """Run every step from `here` to `there`. Returns the backup folder, if it wrote."""
    steps = plan(here, there)
    print(f"Data dir: {data_dir}\nLayout {here} -> {there}, {len(steps)} step(s):")
    for step in steps:
        print(f"  {step} -> {step + 1}  {STEPS[step].__module__.rsplit('.', 1)[-1]}")
    if not steps:
        return None

    into = backup(data_dir) if apply else None
    for step in steps:
        print(f"\n--- layout {step} -> {step + 1} ---")
        STEPS[step](data_dir, apply)

    if into is None:
        print("\nDry run — pass --apply to write.")
        return None
    prune(data_dir)
    print(f"\nDone: layout {there}.\nBackup: {into}\nRevert: cp -a {into}/. {data_dir}/")
    return into
