"""Layout 10 -> 11: the organisation names its overview columns in one list.

A column used to be a flag on each field (`column: true`), and three kinds --
status, user and termijn -- carried that flag by default. The order on screen
was then the order the fields happened to be declared in. An organisation now
writes the columns it wants under `org:`, in the order they must stand:

    org:
      columns: [aangemaakt, gewijzigd, status, behandelaar, termijn]

This script reads the columns the data dir showed, writes them as that list,
and deletes every `column:` line. The table looks the same after the step.

Stdlib only, so a migration keeps running against a data dir the app cannot load.
Dry run by default; pass `apply` to write. Idempotent: a second run reports zero
actions.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# The kinds that used to be a column without saying so.
COLUMN_KINDS = ("status", "user", "termijn")
INTAKE = "aangemaakt"  # the code put the date of intake in front of the rest

# A field declaration inside `types:`: the key at four spaces, its body deeper.
FIELD_RE = re.compile(r"^ {4}(\w+):(.*(?:\n(?: {5,}.*)?)*)", re.MULTILINE)
KIND_RE = re.compile(r"\btype:\s*(\w+)")
FLAG_RE = re.compile(r"\bcolumn:\s*(true|false)")

FLAG_LINE_RE = re.compile(r"^ +column:\s*(?:true|false).*\n", re.MULTILINE)
ORG_RE = re.compile(r"^org:\n((?: +\S.*\n|\n(?= +\S))*)", re.MULTILINE)
VERSION_RE = re.compile(r"^version:\s*10\b", re.MULTILINE)


def columns_of(text: str) -> list[str]:
    """The columns this config showed, in the order the table showed them."""
    found = [INTAKE]
    for key, body in FIELD_RE.findall(text):
        flag = FLAG_RE.search(body)
        marked = flag.group(1) == "true" if flag else _kind_of(body) in COLUMN_KINDS
        if marked and key not in found:
            found.append(key)
    return found


def _kind_of(body: str) -> str:
    kind = KIND_RE.search(body)
    return kind.group(1) if kind else ""


def _with_columns(text: str, columns: list[str]) -> str:
    """Write the list into the `org:` section, making that section if there is none."""
    line = f"  columns: [{', '.join(columns)}]\n"
    if ORG_RE.search(text):
        return ORG_RE.sub(lambda m: m.group(0) + line, text, count=1)
    return VERSION_RE.sub(lambda m: m.group(0) + f"\n\norg:\n{line.rstrip()}", text, count=1)


def migrate_config(config: Path, apply: bool) -> int:
    """Name the columns under `org:`, drop the flags, and stamp version 11."""
    text = config.read_text(encoding="utf8")
    if not VERSION_RE.search(text):  # already at 11: the list is written, the flags are gone
        return 0
    new = _with_columns(FLAG_LINE_RE.sub("", text), columns_of(text))
    new = VERSION_RE.sub("version: 11", new)
    if new == text:
        return 0
    if apply:
        config.write_text(new, encoding="utf8")
    print(f"  {'migrate' if apply else '[dry] migrate'} {config}")
    return 1


def main(data_dir: Path, apply: bool) -> int:
    config = data_dir / ".app" / "config.yaml"
    if not config.is_file():
        sys.exit(f"ERROR: {config} not found. Is {data_dir} an ODAS data dir?")

    print(f"Data dir: {data_dir}\n  columns: {', '.join(columns_of(config.read_text('utf8')))}\n")
    changed = migrate_config(config, apply)

    print(f"\n{changed} file(s) {'changed' if apply else 'to change'}.")
    if not apply and changed:
        print("Dry run -- pass --apply to write.")
    return changed
