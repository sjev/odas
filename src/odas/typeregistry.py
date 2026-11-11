"""Resolve the `types:` registry before any field is parsed.

A type *is* its field declaration, with three exceptions. `extends` names one
parent whose fields come first, `public_intake` marks the single type the public
form creates, and `prefix` gives the two letters in front of a new ref of that
type. None is a field, so all three are stripped here and everything that
reaches the field parser is a field.

Two rules hold the shape:

- **One level, never a chain.** A parent that itself extends is refused, so a
  reader sees a whole type in two places rather than five.
- **A child restates, never removes.** Naming a parent's key replaces that
  declaration whole and keeps the parent's position, so the order on disk does
  not shift when a child narrows one field. Removing a field is not possible:
  if a child must not have it, the parent was wrong.

This is composition inside one file, not merging. The ban on merging is about a
second file, and it still holds: a reader sees both types in the same config.

Below `resolve()` sits the expansion half: how a `types:` mapping becomes `Field`
objects. A value is a type -- a scalar name, `list[<scalar>]`, or a list of
literals meaning an enum. The long form puts the same value under `type:` and
adds label/hint/flags beside it. Declaration order is the order on disk and in
the UI, and a field that is not declared does not exist.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import BeforeValidator

from odas.fields import FIELD_TYPES, Field

EXTENDS = "extends"
PUBLIC_INTAKE = "public_intake"
PREFIX = "prefix"
RESERVED = (EXTENDS, PUBLIC_INTAKE, PREFIX)

# What a type gets when it declares no prefix: the ref every data dir minted
# before a type could name its own.
DEFAULT_PREFIX = "zk"
# `naming.looks_like_ref` reads this shape, and `folder_store.ref_from_folder`
# splits a folder name on its second hyphen. So a prefix holds no hyphen.
PREFIX_RE = re.compile(r"[a-z]{2}")

# Injected in front of every type's own declarations, in this order.
BASE_TYPE_SPECS: dict[str, Any] = {
    "id": {"type": "ref", "label": "Referentie", "required": True, "editable": []},
    "soort": {"type": "soort", "hint": "type zaak, bepaalt de velden", "editable": []},
    "titel": {"type": "str", "public": True, "editable": ["team"]},
    "aangemaakt": {"type": "datetime", "hint": "ISO tijdstip, niet wijzigen", "editable": []},
    "gewijzigd": {"type": "datetime", "hint": "ISO tijdstip, bij elke wijziging", "editable": []},
}

# A log entry keeps the same two moments; the day and the order stay in its name.
BASE_LOG_SPECS: dict[str, Any] = {k: BASE_TYPE_SPECS[k] for k in ("aangemaakt", "gewijzigd")}


def _fields_of(spec: dict[str, Any]) -> dict[str, Any]:
    """The declaration without the two keys that are capabilities, not fields."""
    return {k: v for k, v in spec.items() if k not in RESERVED}


def _intake_type(specs: dict[str, dict[str, Any]]) -> str:
    """The one type the public form creates, or "" when no type claims it."""
    named = [name for name, spec in specs.items() if spec.get(PUBLIC_INTAKE)]
    if len(named) > 1:
        raise ValueError(
            f"two types declare public_intake: {', '.join(repr(n) for n in named)}. "
            "There is one public form, so exactly one type may own it."
        )
    return named[0] if named else ""


def _prefixes(specs: dict[str, dict[str, Any]]) -> dict[str, str]:
    """The two letters in front of a new ref, per type. An undeclared type keeps `zk`."""
    found = {}
    for name, spec in specs.items():
        value = str(spec.get(PREFIX, DEFAULT_PREFIX))
        if not PREFIX_RE.fullmatch(value):
            raise ValueError(
                f"type {name!r} declares prefix {value!r}: a prefix is exactly two "
                "lowercase letters, such as 'zk'."
            )
        found[name] = value
    return found


def resolve(raw: Any) -> tuple[Any, str, dict[str, str]]:
    """Return the registry with `extends` applied, the intake type, and the ref prefixes."""
    if not isinstance(raw, dict):
        return raw, "", {}

    specs = {name: dict(spec or {}) for name, spec in raw.items()}
    intake = _intake_type(specs)
    prefixes = _prefixes(specs)

    resolved: dict[str, Any] = {}
    for name, spec in specs.items():
        parent = spec.get(EXTENDS) or ""
        fields = _fields_of(spec)
        if parent:
            if parent not in specs:
                raise ValueError(f"type {name!r} extends unknown type {parent!r}.")
            if specs[parent].get(EXTENDS):
                raise ValueError(
                    f"type {name!r} extends {parent!r}, which extends further: "
                    "extends is one level, never a chain."
                )
            fields = {**_fields_of(specs[parent]), **fields}
        resolved[name] = fields
    return resolved, intake, prefixes


def _as_field(key: str, value: Any) -> Field:
    """Expand shorthand `"str"` / `"list[email]"` / `[a, b, c]` and instantiate the type."""
    spec = dict(value) if isinstance(value, dict) else {"type": value}
    kind = spec.pop("type", "str")
    if isinstance(kind, list):
        spec["options"] = kind
        kind = "enum"
    cls = FIELD_TYPES.get(kind)
    if cls is None:
        raise ValueError(f"unknown type {kind!r}; choose from: {', '.join(FIELD_TYPES)}")
    spec.setdefault("label", key.replace("_", " ").capitalize())
    return cls(**spec)


def as_fields(value: Any) -> Any:
    """Expand every field in a section and default its label from the key."""
    if not isinstance(value, dict):
        return value
    return {key: _as_field(key, spec) for key, spec in value.items()}


Fields = Annotated[dict[str, Field], BeforeValidator(as_fields)]

BASE_FIELDS: dict[str, Field] = as_fields(BASE_TYPE_SPECS)


def _with_base_fields(value: Any) -> Any:
    """Inject the base fields in front of every declared type."""
    if not isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    for name, spec in value.items():
        redeclared = set(spec or {}) & set(BASE_TYPE_SPECS)
        if redeclared:
            raise ValueError(
                f"type {name!r} may not redeclare base key(s): {', '.join(sorted(redeclared))}"
            )
        out[name] = {**BASE_TYPE_SPECS, **(spec or {})}
    return out


TypeRegistry = Annotated[dict[str, Fields], BeforeValidator(_with_base_fields)]
