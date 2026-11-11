"""Data/app compatibility.

`config.yaml` declares the layout revision it was written for. The app needs the
layout `DATA_VERSION` names, because the parts of the on-disk contract the config
cannot describe -- the single `zaken/` store, the log entry name grammar -- live
in code and change together with a migration.

A data dir that is behind is migrated at start: `ensure()` backs it up, runs every
step in `odas.migrations`, and then serves it. A data dir that is ahead refuses to
run, because this app does not know the layout it declares.

This is deliberately not the release version: a data dir is migrated far less
often than the app is tagged, so DATA_VERSION moves only when a migration has to
run first.
"""

from __future__ import annotations

import fcntl
import logging
from pathlib import Path

from odas import appconfig, configload, migrations

DATA_VERSION = 13

LOCK_FILE = ".migrating"

log = logging.getLogger(__name__)


def read_version(data_dir: str | None = None) -> int | None:
    """The layout revision this data dir declares, or None if it declares none."""
    version = configload.resolve(data_dir).get("version")
    return version if isinstance(version, int) else None


def ensure() -> None:
    """Serve this data dir at layout DATA_VERSION, migrating it first if it is behind."""
    path = configload.config_path()
    data_dir = path.parent.parent
    version = read_version()

    if version is None:
        raise SystemExit(
            f"{path} declares no `version:` (data: {data_dir}).\n"
            "A data dir this old is taken up by hand: see scripts/README.md."
        )
    if version == DATA_VERSION:
        return
    if version > DATA_VERSION:
        raise SystemExit(
            f"This data dir is written for layout {version}, and this app serves "
            f"{DATA_VERSION} (data: {data_dir}).\n"
            "Upgrade the app, or check that ODAS_DATA_DIR points at the right directory."
        )
    _migrate(data_dir)


def _migrate(data_dir: Path) -> None:
    """Run the migrations, with the web and the mail container taking turns."""
    lock = data_dir / ".app" / LOCK_FILE
    lock.touch()
    with lock.open("r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        version = read_version()  # the other container may have just done the work
        if version == DATA_VERSION:
            return
        assert version is not None
        backups = data_dir / migrations.BACKUP_DIR
        try:
            into = migrations.run(data_dir, version, DATA_VERSION, apply=True)
            appconfig.get_config.cache_clear()  # the served config is the migrated one
        except Exception as error:  # a part-way data dir must say so, and stop
            log.exception(
                f"Migration failed: layout {version} -> {DATA_VERSION}, revert from {str(backups)!r}"
            )
            raise SystemExit(f"Migration failed: {error}\nRevert from {backups}.") from error

        log.info(f"Data dir migrated: layout {version} -> {DATA_VERSION} backup={str(into)!r}")

    reached = read_version()
    if reached != DATA_VERSION:
        raise SystemExit(f"Migration ended at layout {reached}, not {DATA_VERSION}.")
