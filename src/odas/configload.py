"""Read the data dir's schema.

A data dir owns its schema: `$ODAS_DATA_DIR/.app/config.yaml` declares the
`types:` registry, the `fields.log` section and the `org:` settings, and it is
complete. Nothing is merged onto it and nothing merges behind it -- what the
file does not declare does not exist for this organisation.

`odas init` writes a new data dir its first config from TEMPLATE.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

TEMPLATE = Path(__file__).resolve().parent / "builtin" / "generic.yaml"
SITE_FILE = ".app/config.yaml"

MISSING_HINT = (
    "This data dir has no schema. Run `odas init` to write one, or check that "
    "ODAS_DATA_DIR points at the right directory."
)


class _StrictLoader(yaml.SafeLoader):
    """A loader that refuses a key declared twice in the same mapping.

    YAML keeps the last of two equal keys and drops the first without a word. A
    second `mailin:` then quietly undoes the first, and the setting a person
    wrote does not exist. The file is rejected instead, and the key is named.
    """


def _no_duplicate_keys(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            line = key_node.start_mark.line + 1
            raise ValueError(f"line {line}: {key!r} is declared twice; the first one is lost.")
        seen.add(key)
    return loader.construct_mapping(node, deep=True)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _no_duplicate_keys,
)


def data_root() -> Path:
    """`ODAS_DATA_DIR`, else the directory odas runs in."""
    return Path(os.getenv("ODAS_DATA_DIR") or Path.cwd())


def config_path(data_dir: str | None = None) -> Path:
    """Where this data dir keeps its schema."""
    root = data_root() if data_dir is None else Path(data_dir)
    return root / SITE_FILE


def resolve(data_dir: str | None = None) -> dict[str, Any]:
    """The data dir's schema, as a plain dict."""
    path = config_path(data_dir)
    if not path.is_file():
        raise ValueError(f"{path} does not exist.\n{MISSING_HINT}")
    try:
        loaded = yaml.load(path.read_text(encoding="utf8"), Loader=_StrictLoader) or {}
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from e
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: configuration must be a mapping.")
    return loaded
