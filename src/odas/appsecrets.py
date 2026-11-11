"""Read the data dir's secrets.

Credentials are the one thing that does not belong in `config.yaml`: that file is
the data dir's schema and is meant to be read, diffed and copied. They live beside
it in `$ODAS_DATA_DIR/.app/secrets.yaml`, mode 0600, like the session key file.

The environment is not a source. A deployment delivers this file; an env var of
the same name is ignored, so there is exactly one place to look.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from odas.configload import data_root

FILE_MODE = 0o600
SECRETS_FILE = ".app/secrets.yaml"

TEMPLATE = """\
# Credentials for this data dir. Keep this file mode 0600 and out of version
# control. Everything that is not a secret belongs in config.yaml.
oidc_client_secret: ""
pocket_id_api_key: ""
smtp_pass: ""
ai_api_key: ""
"""


class AppSecrets(BaseModel):
    """The credentials a deployment supplies. Empty means "not configured"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    oidc_client_secret: str = ""
    pocket_id_api_key: str = ""
    smtp_pass: str = ""
    ai_api_key: str = ""


def secrets_path(data_dir: str | None = None) -> Path:
    """Where this data dir keeps its credentials."""
    root = data_root() if data_dir is None else Path(data_dir)
    return root / SECRETS_FILE


@lru_cache(maxsize=1)
def get_secrets() -> AppSecrets:
    """The data dir's credentials. Cached: edits need a restart, like the config."""
    path = secrets_path()
    if not path.is_file():
        return AppSecrets()
    loaded = yaml.safe_load(path.read_text(encoding="utf8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: secrets must be a mapping.")
    os.chmod(path, FILE_MODE)  # a credential file that others can read is a finding
    return AppSecrets(**loaded)


def require(name: str) -> str:
    """A credential the caller cannot work without."""
    value = getattr(get_secrets(), name)
    if not value:
        raise ValueError(f"{name} is not set. Add it to {secrets_path()}.")
    return str(value)
