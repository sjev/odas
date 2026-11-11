"""Canonical frontmatter serialization and validation.

Field declarations themselves live in `appconfig`; this module only reads them.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import yaml

from odas.appconfig import Field, Option, log_fields

__all__ = [
    "Field",
    "Option",
    "dump",
    "frontmatter",
    "log_fields",
    "parse",
    "parse_or_raw",
    "undeclared",
    "validate",
]

_UNKNOWN_FIELD = Field(hint="onbekend veld (niet in schema)")


def _coerce(value: Any) -> str:
    """Frontmatter values are always strings; normalize what yaml gives back."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return ", ".join(_coerce(v) for v in value)
    return str(value)


def parse(text: str) -> tuple[dict[str, str], str]:
    """Split an index.md / log entry into (frontmatter, body). Raises yaml.YAMLError on bad frontmatter."""
    if not text.startswith("---"):
        return {}, text.strip()
    parts = text.split("---", 2)
    if len(parts) != 3:
        raise yaml.YAMLError("Frontmatter-blok is niet afgesloten met ---.")
    loaded = yaml.safe_load(parts[1]) or {}
    if not isinstance(loaded, dict):
        raise yaml.YAMLError("Frontmatter moet een lijst 'sleutel: waarde' regels zijn.")
    return {str(k): _coerce(v) for k, v in loaded.items()}, parts[2].strip()


def parse_or_raw(raw: str) -> tuple[dict[str, str], str, bool]:
    """Parse raw text; on bad frontmatter fall back to (empty fm, raw as body, True)."""
    try:
        fm, body = parse(raw)
        return fm, body, False
    except Exception:
        return {}, raw, True


def _needs_quote(value: str) -> bool:
    if value == "":
        return False
    if value != value.strip() or any(c in value for c in "#:\n"):
        return True
    return value[0] in "!&*?|>%@`\"'[]{},-"


def _dump_value(value: str) -> str:
    return json.dumps(value, ensure_ascii=False) if _needs_quote(value) else value


def _dump_field(key: str, f: Field, value: str) -> list[str]:
    comment = f.comment(key)
    if f.multi and value:
        line = f"{key}:"
        if comment:
            line = f"{line.ljust(24)} # {comment}"
        items = [f"  - {item}" for item in (s.strip() for s in value.split(",")) if item]
        return [line, *items]
    line = f"{key}: {_dump_value(value)}".rstrip()
    if comment:
        line = f"{line.ljust(24)} # {comment}"
    return [line]


def frontmatter(values: dict[str, Any], body: str) -> str:
    """Frontmatter + body for a file that owns no schema: a law, a cache file."""
    dumped = yaml.safe_dump(values, sort_keys=False, allow_unicode=True)
    return f"---\n{dumped}---\n\n{body.strip()}\n"


def dump(values: dict[str, str], body: str, fields: dict[str, Field]) -> str:
    """Serialize canonical frontmatter (all fields, in order, documented) + body.

    Keys not in `fields` are kept at the end: a schema change must never silently
    drop data that is already on disk.
    """

    def clean(key: str) -> str:
        return (values.get(key) or "").strip().replace("\n", " ")

    lines = ["---"]
    written = set()
    for key, f in fields.items():
        for k in f.disk_keys(key):
            lines += _dump_field(k, f, clean(k))
            written.add(k)
    for key in values:
        if key not in written:
            lines += _dump_field(key, _UNKNOWN_FIELD, clean(key))
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"


def undeclared(fm: dict[str, str], fields: dict[str, Field]) -> dict[str, str]:
    """The on-disk keys this schema does not declare, in file order.

    A schema change leaves keys behind. They are shown and kept, never hidden and
    never dropped: the page and the file must give the same answer.
    """
    declared = {k for key, f in fields.items() for k in f.disk_keys(key)}
    return {k: v for k, v in fm.items() if k not in declared}


def validate(fm: dict[str, str], fields: dict[str, Field]) -> None:
    """Raise ValueError (Dutch) if a required field is empty or an enum value is unknown."""
    for key, f in fields.items():
        f.check(key, fm)
