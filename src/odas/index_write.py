"""Edit an existing zaak's index.md: raw-text parsing, single/bulk field updates.

The field declaration is resolved from the record itself -- its `soort:` names the
type -- so callers never pass one in. `update_index` resolves from the *incoming*
text, which is what makes retyping a zaak possible.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from odas import audit, schema, zaak
from odas.appconfig import default_type_name, field_for_key, type_fields
from odas.fields import FlagField, StatusField, declared_key
from odas.zaak_create import write_index

log = logging.getLogger(__name__)


def parse_raw(raw_text: str) -> tuple[dict[str, str], str]:
    """Split editor text into (frontmatter, body). Raises ValueError (Dutch) on bad input."""
    if not raw_text.startswith("---"):
        raise ValueError("Tekst moet beginnen met een frontmatter-blok (---).")
    try:
        return schema.parse(raw_text)
    except yaml.YAMLError as e:
        raise ValueError(f"Ongeldige frontmatter: {e}") from e


def _label(fields: dict[str, schema.Field], key: str) -> str:
    """The UI label for a disk key, which may be one of a field's extra_keys."""
    f = field_for_key(fields, key)
    return f.label if f else key


def set_field(folder: Path, key: str, value: str, by: str) -> None:
    """Set one frontmatter field, re-serialize canonically, append an audit line."""
    z = zaak.load(folder)
    fields = z.fields
    if field_for_key(fields, key) is None:
        raise ValueError(f"Onbekend veld: {key}")
    old = z.frontmatter.get(key, "")
    fm = dict(z.frontmatter)
    fm[key] = value
    schema.validate(fm, fields)
    write_index(folder, fm, z.body, fields)
    audit.write(folder, f"{_label(fields, key)} gewijzigd: {old or '—'} → {value or '—'}", by)
    if key == declared_key(fields, StatusField):
        log.info(f"Status changed: ref={folder.name!r} {old!r} -> {value!r} by={by!r}")


def set_flag(folder: Path, on: bool, by: str) -> None:
    """Set or clear the flag field. A type that declares none has nothing to set.

    No validation: a message must land on a zaak with a fault.
    """
    z = zaak.load(folder)
    key = declared_key(z.fields, FlagField)
    old, new = z.frontmatter.get(key, ""), "ja" if on else ""
    if not key or old == new:
        return
    write_index(folder, {**z.frontmatter, key: new}, z.body, z.fields)
    audit.write(folder, f"{_label(z.fields, key)} gewijzigd: {old or '—'} → {new or '—'}", by)


def update_fields(folder: Path, updates: dict[str, str], by: str) -> None:
    """Update a subset of frontmatter fields in one write; other fields untouched.

    Raises `ValueError` on an unknown field or failed schema validation.
    """
    z = zaak.load(folder)
    fields = z.fields
    fm = dict(z.frontmatter)
    for key, value in updates.items():
        if field_for_key(fields, key) is None:
            raise ValueError(f"Onbekend veld: {key}")
        fm[key] = value
    schema.validate(fm, fields)
    write_index(folder, fm, z.body, fields)
    changed = [
        f"{_label(fields, k)}: {z.frontmatter.get(k) or '—'} → {fm.get(k) or '—'}"
        for k in updates
        if fm.get(k, "") != z.frontmatter.get(k, "")
    ]
    audit.write(folder, "index bewerkt" + (f" ({'; '.join(changed)})" if changed else ""), by)


def update_index(folder: Path, raw_text: str, by: str) -> None:
    """Overwrite index.md with validated raw text and log the edit. Raises `ValueError` on bad input."""
    fm, body = parse_raw(raw_text)
    existing = zaak.load(folder)
    if fm.get("id") != existing.ref:
        raise ValueError(f"De id mag niet wijzigen (verwacht {existing.ref}).")
    # Retyping is allowed, so the new text decides which fields apply.
    soort = fm.get("soort") or default_type_name()
    fields = type_fields(soort)
    schema.validate(fm, fields)

    write_index(folder, fm, body, fields)
    if soort != existing.soort:
        audit.write(folder, f"Soort gewijzigd: {existing.soort or '—'} → {soort}", by)
    # Identity is reported by its own line above; the stamps are no edit.
    silent = ("id", "soort", "aangemaakt", "gewijzigd")
    changed = [
        f"{f.label}: {existing.frontmatter.get(k) or '—'} → {fm.get(k) or '—'}"
        for key, f in fields.items()
        for k in f.disk_keys(key)
        if fm.get(k, "") != existing.frontmatter.get(k, "") and k not in silent
    ]
    msg = "index bewerkt" + (f" ({'; '.join(changed)})" if changed else "")
    audit.write(folder, msg, by)
    status = declared_key(fields, StatusField)
    if status and fm.get(status, "") != existing.frontmatter.get(status, ""):
        log.info(
            f"Status changed: ref={folder.name!r}"
            f" {existing.frontmatter.get(status)!r} -> {fm.get(status)!r}"
            f" by={by!r}"
        )
