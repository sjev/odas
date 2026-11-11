"""Layout 5 → 6: ODAS stops sending correspondence and starts capturing it.

A jurist now writes and sends in their own mail client and puts the zaak address
in Bcc; the copy that arrives is filed whole. So `fields.log` no longer holds a
`bcc` (a Bcc'd copy carries no such header) or a `verzonden` stamp (the message
carries its own date), and it gains `van` and `message_id`, which are read off
the message rather than typed.

The script rewrites `fields.log` in the config, drops the two dead keys from
every log entry on disk, and stamps version 6. It does *not* invent a `mailin:`
section: the domain is a deployment decision. Add it by hand afterwards:

    mailin:
      domains: [odas.example.nl]
      key: ""            # set it when several data dirs share one domain

Stdlib only, so a migration keeps running against a data dir the app cannot load.
Dry run by default; pass `apply` to write. Idempotent: a second run reports zero
actions.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# A frontmatter key and everything under it, including any `  - item` block.
DEAD_KEY_RE = re.compile(r"^(?:bcc|verzonden):.*\n(?:[ \t]+-.*\n)*", re.MULTILINE)

# The `aan:` declaration in fields.log, from its key to the line before the next
# key at the same indent. The whole mail block is replaced in one go.
LOG_BLOCK_RE = re.compile(
    r"^(?P<indent>[ \t]+)aan:\n(?:[ \t]{6,}.*\n|\n)*"
    r"(?:[ \t]+(?:cc|bcc|verzonden):\n(?:[ \t]{6,}.*\n|\n)*)*",
    re.MULTILINE,
)

NEW_LOG_BLOCK = """{i}van:
{i}  type: email
{i}  editable: []
{i}  hint: "systeem: afzender"
{i}aan:
{i}  type: list[email]
{i}  editable: []
{i}  hint: "systeem: ontvangers"
{i}cc:
{i}  type: list[email]
{i}  editable: []
{i}  hint: "systeem: meelezers"
{i}message_id:
{i}  type: str
{i}  editable: []
{i}  hint: "systeem: kenmerk van het bericht, houdt dubbele kopieen eruit"
"""

VERSION_RE = re.compile(r"^version:\s*5\b", re.MULTILINE)

# The comment above `log:`, which described the outbox the app no longer is.
OLD_COMMENT_RE = re.compile(r"^[ \t]*#[^\n]*\n(?:[ \t]*#[^\n]*\n)*(?=[ \t]+log:\n)", re.MULTILINE)
NEW_COMMENT = """  # log/ entry frontmatter, read from the message that came in. Date (JJJJ-MM-DD)
  # and direction (IN/UIT/LOG) live in the entry name, so neither appears here.
  # ODAS composes no mail: a jurist sends from their own client and puts the zaak
  # address in Bcc, and the copy that arrives is filed whole. So every key below
  # except onderwerp is `editable: []` -- it is read off the message, never typed.
"""


def _rewrite(path: Path, text: str, new: str, what: str, apply: bool) -> int:
    if new == text:
        return 0
    if apply:
        path.write_text(new, encoding="utf8")
        print(f"  {what} {path}")
    else:
        print(f"  [dry] {what} {path}")
    return 1


def log_entries(data_dir: Path) -> list[Path]:
    """Every log entry's text file: flat `<stem>.md` and `<stem>/index.md` alike."""
    log_dirs = (p for p in (data_dir / "zaken").glob("*/log") if p.is_dir())
    found: list[Path] = []
    for log_dir in log_dirs:
        found += sorted(log_dir.glob("*.md"))
        found += sorted(log_dir.glob("*/index.md"))
    return found


def migrate_entry(path: Path, apply: bool) -> int:
    """Drop `bcc:` and `verzonden:`; the app no longer sends, so neither has meaning."""
    text = path.read_text(encoding="utf8")
    head, sep, rest = text.partition("---\n")
    if not sep:  # no frontmatter block: nothing addressed here
        return 0
    block, sep2, body = rest.partition("---\n")
    new = head + sep + DEAD_KEY_RE.sub("", block) + sep2 + body
    return _rewrite(path, text, new, "clean", apply)


def migrate_config(config: Path, apply: bool) -> int:
    """Replace the mail keys in `fields.log` and stamp version 6."""
    text = config.read_text(encoding="utf8")
    match = LOG_BLOCK_RE.search(text)
    new = text
    if match and "message_id:" not in text:
        new = text[: match.start()] + NEW_LOG_BLOCK.format(i=match["indent"]) + text[match.end() :]
        new = OLD_COMMENT_RE.sub(NEW_COMMENT, new)
    new = VERSION_RE.sub("version: 6", new)
    changed = _rewrite(config, text, new, "migrate", apply)
    if changed and "mailin:" not in new:
        print("  NOTE: add a `mailin:` section to switch capture on (see this script's docstring).")
    return changed


def main(data_dir: Path, apply: bool) -> None:
    config = data_dir / ".app" / "config.yaml"
    if not config.is_file():
        sys.exit(f"ERROR: {config} not found. Is {data_dir} an ODAS data dir?")

    entries = log_entries(data_dir)
    print(f"Data dir: {data_dir}  ({len(entries)} log entries)\n")

    changed = migrate_config(config, apply)
    for entry in entries:
        changed += migrate_entry(entry, apply)

    print(f"\n{changed} file(s) {'changed' if apply else 'to change'}.")
    if not apply and changed:
        print("Dry run — pass --apply to write.")
