"""Where things are on disk, plus the two environment variables ODAS still reads.

Everything else a deployment sets lives in the data dir: `.app/config.yaml` for
settings, `.app/secrets.yaml` for credentials.
"""

from __future__ import annotations

import os
from pathlib import Path

from odas.appconfig import get_config
from odas.configload import data_root
from odas.settings import OrgProfile


class Config:
    """Paths derived from ODAS_DATA_DIR, and the dev auth bypass."""

    @property
    def org(self) -> OrgProfile:
        """Branding and feature flags, as the data dir declares them."""
        return get_config().org

    @property
    def test_mode(self) -> bool:
        """Local-dev auth bypass (set by start_dev.sh). Never set in prod."""
        return os.getenv("ODAS_TEST_MODE") is not None

    @property
    def root(self) -> Path:
        """Single data root; holds `.app/` and `zaken/`."""
        return data_root()

    @property
    def data_dir(self) -> Path:
        """The schema (`config.yaml`) plus runtime state (`.secret_key`, users, `logs/`)."""
        return self.root / ".app"

    @property
    def log_dir(self) -> Path:
        """One file per entry point; two containers share one volume."""
        return self.data_dir / "logs"

    def log_file(self, name: str) -> Path:
        """The file for one entry point: `app` or `mail`."""
        return self.log_dir / f"{name}.log"

    def mail_cert(self) -> tuple[Path, Path]:
        """The pair the mail daemon offers over STARTTLS. It makes one if absent."""
        return self.data_dir / "mail.crt", self.data_dir / "mail.key"

    @property
    def users_file(self) -> Path:
        """JSONL store of team users."""
        return self.data_dir / "users.jsonl"

    @property
    def zaken_dir(self) -> Path:
        """Root folder holding one subfolder per zaak."""
        return self.root / "zaken"

    @property
    def prullenbak_dir(self) -> Path:
        """Where a deleted zaak goes. Delete is a move, so nothing here is emptied."""
        return self.root / "prullenbak"

    @property
    def wetten_dir(self) -> Path:
        """Cached law text, one subfolder per tracked law. Absent means none is tracked."""
        return self.root / "wetten"

    def ensure_dirs(self) -> None:
        """Create the writable state dir. Called once at startup, not per read."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
