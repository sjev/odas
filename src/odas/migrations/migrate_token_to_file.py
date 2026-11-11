"""Layout 8 → 9: the reply token moves out of the case record.

`reply_token:` sat in the frontmatter of every `index.md`. It is a bearer
capability: the string alone opens `/inzien-<token>`, with no account and no
expiry. It gave no new access to a reader who already held the folder, but it
travelled onward with everything that carried the case -- an export, a backup,
and above all an agent that reads `index.md` into a model's context.

This script lifts the value into `.access-token`, one file beside `index.md`,
mode 0600. The type declaration in `config.yaml` stays where it is: it is the
switch that says a type is shareable by link, and only the storage moves.

Every token already minted is carried over, so no link mailed to an indiener
stops working. To burn them instead, delete the `.access-token` files after this
run; the app mints a new one when the zaak is next created, not on read, so a
burn needs a fresh link sent by hand.

`prullenbak/` is migrated too: a restored zaak keeps its link.

Stdlib only, so a migration keeps running against a data dir the app cannot load.
Dry run by default; pass `apply` to write. Idempotent: a second run reports zero
actions.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TOKEN_FILE = ".access-token"
TOKEN_MODE = 0o600
VERSION_RE = re.compile(r"^version:\s*8\b", re.MULTILINE)
STORES = ("zaken", "prullenbak")


def token_line(key: str) -> re.Pattern[str]:
    """`<key>: <value>` on its own frontmatter line, with any trailing comment."""
    return re.compile(rf"^{re.escape(key)}:[ \t]*(\S+)[ \t]*(?:#.*)?\n", re.MULTILINE)


def folders(data_dir: Path) -> list[Path]:
    """Every record folder that holds an index.md, in both stores."""
    return sorted(
        p
        for store in STORES
        if (data_dir / store).is_dir()
        for p in (data_dir / store).iterdir()
        if p.is_dir() and (p / "index.md").is_file()
    )


def move(folder: Path, pattern: re.Pattern[str], apply: bool) -> int:
    """Lift the token out of one index.md and into its own file."""
    index = folder / "index.md"
    text = index.read_text(encoding="utf8")
    found = pattern.search(text)
    if not found:
        return 0

    target = folder / TOKEN_FILE
    if apply:
        target.write_text(found.group(1) + "\n", encoding="utf8")
        target.chmod(TOKEN_MODE)
        index.write_text(pattern.sub("", text, count=1), encoding="utf8")
        print(f"  move {target}")
    else:
        print(f"  [dry] move {target}")
    return 1


def stamp(config: Path, apply: bool) -> int:
    text = config.read_text(encoding="utf8")
    new = VERSION_RE.sub("version: 9", text)
    if new == text:
        return 0
    if apply:
        config.write_text(new, encoding="utf8")
        print(f"  version 9 {config}")
    else:
        print(f"  [dry] version 9 {config}")
    return 1


def main(data_dir: Path, apply: bool, key: str = "reply_token") -> int:
    config = data_dir / ".app" / "config.yaml"
    if not config.is_file():
        sys.exit(f"ERROR: {config} not found. Is {data_dir} an ODAS data dir?")

    found = folders(data_dir)
    print(f"Data dir: {data_dir}  ({len(found)} record folders, token key `{key}`)\n")

    pattern = token_line(key)
    changed = stamp(config, apply) + sum(move(f, pattern, apply) for f in found)

    print(f"\n{changed} file(s) {'changed' if apply else 'to change'}.")
    print(f"Keep `{key}:` in config.yaml: the declaration stays, only the value moves.")
    if not apply and changed:
        print("Dry run — pass --apply to write.")
    return changed
