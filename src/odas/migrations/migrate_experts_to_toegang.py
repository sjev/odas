"""Layout 4 → 5: the `experts` field becomes `toegang`, and `group_experts` goes.

Access used to be two things: an `expert` role from an OIDC group, plus an
`experts:` field naming who held a grant. It is now one rule -- the team group
opens every zaak, a zaak's `toegang:` field opens that one -- and whoever gets in
may edit. Anyone who was an external expert keeps exactly the zaken that named
them, so this migration only renames.

Stdlib only, so a migration keeps running against a data dir the app cannot load.
Dry run by default; pass `apply` to write. Idempotent: a second run reports zero
actions.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

OLD_HINT = "e-mails van externe experts met toegang"
NEW_HINT = "e-mails van personen met toegang tot deze zaak"
OLD_NOTE = "this field *is* the expert access grant"
NEW_NOTE = "this field *is* the access grant"

# `experts:` at the start of a frontmatter line, with whatever trails it.
KEY_RE = re.compile(r"^experts:", re.MULTILINE)
FIELD_RE = re.compile(r"^(\s*)experts:$", re.MULTILINE)
TYPE_RE = re.compile(r"^(\s*)type:\s*experts\b", re.MULTILINE)
GROUP_RE = re.compile(r"^\s*#?\s*group_experts:.*\n", re.MULTILINE)
VERSION_RE = re.compile(r"^version:\s*4\b", re.MULTILINE)


def _rewrite(path: Path, text: str, new: str, what: str, apply: bool) -> int:
    if new == text:
        return 0
    if apply:
        path.write_text(new, encoding="utf8")
        print(f"  {what} {path}")
    else:
        print(f"  [dry] {what} {path}")
    return 1


def migrate_zaak(index: Path, apply: bool) -> int:
    """Rename the `experts:` frontmatter key and refresh its trailing comment."""
    text = index.read_text(encoding="utf8")
    new = KEY_RE.sub("toegang:", text).replace(OLD_HINT, NEW_HINT)
    return _rewrite(index, text, new, "rename key in", apply)


def migrate_config(config: Path, apply: bool) -> int:
    """Rename the field and its type, drop `group_experts`, and stamp version 5."""
    text = config.read_text(encoding="utf8")
    new = FIELD_RE.sub(r"\1toegang:", text)
    new = TYPE_RE.sub(r"\1type: toegang", new)
    new = GROUP_RE.sub("", new)
    new = VERSION_RE.sub("version: 5", new)
    new = new.replace(OLD_HINT, NEW_HINT).replace(OLD_NOTE, NEW_NOTE)
    return _rewrite(config, text, new, "migrate", apply)


def main(data_dir: Path, apply: bool) -> None:
    config = data_dir / ".app" / "config.yaml"
    if not config.is_file():
        sys.exit(f"ERROR: {config} not found. Is {data_dir} an ODAS data dir?")

    zaken = sorted((data_dir / "zaken").glob("*/index.md"))
    print(f"Data dir: {data_dir}  ({len(zaken)} zaken)\n")

    changed = migrate_config(config, apply)
    for index in zaken:
        changed += migrate_zaak(index, apply)

    print(f"\n{changed} file(s) {'changed' if apply else 'to change'}.")
    if not apply and changed:
        print("Dry run — pass --apply to write.")
