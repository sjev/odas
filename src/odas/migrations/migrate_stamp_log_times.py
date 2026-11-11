"""Layout 11 → 12: a log entry carries the moment it happened.

`aangemaakt:` stands first in the frontmatter of each log entry. The app sets it
when it writes the entry; a received message brings its own `Date:`.

This script fills it in for the mail entries written before: the `Date:` of the
letter a forward carries, else the `Date:` of `bericht.eml`. A typed entry has no
such record, so it gets no stamp and the page shows its date alone.
`prullenbak/` is migrated too.

Stdlib only, so a migration keeps running against a data dir the app cannot load.
Dry run by default; pass `apply` to write. Idempotent: a second run reports zero
actions.
"""

from __future__ import annotations

import re
import sys
from datetime import UTC
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

VERSION_RE = re.compile(r"^version:\s*11\b", re.MULTILINE)
STORES = ("zaken", "prullenbak")
RAW_NAME = "bericht.eml"
HINT = "ISO tijdstip, niet wijzigen"  # as the app writes it: the next save changes nothing
STAMPED = re.compile(r"^aangemaakt:", re.MULTILINE)


def mail_entries(data_dir: Path) -> list[Path]:
    """Every log entry folder that keeps the message it was filed from."""
    return sorted(
        p.parent
        for store in STORES
        if (data_dir / store).is_dir()
        for p in (data_dir / store).glob(f"*/log/*/{RAW_NAME}")
        if (p.parent / "index.md").is_file()
    )


def sent_at(raw: bytes) -> str:
    """The moment the letter was sent, in UTC as the app writes it; "" when unreadable."""
    msg = message_from_bytes(raw, policy=policy.default)
    letters = [
        part.get_payload(0) for part in msg.walk() if part.get_content_type() == "message/rfc822"
    ]
    dates = [letter.get("Date", "") for letter in letters if isinstance(letter, EmailMessage)]
    for value in [*dates, msg.get("Date", "")]:
        try:
            at = parsedate_to_datetime(str(value).strip()).astimezone(UTC)
            return at.isoformat(timespec="seconds")
        except Exception:
            continue
    return ""


def stamp_entry(entry: Path, apply: bool) -> int:
    """Put `aangemaakt:` first, where the next save puts it anyway."""
    index = entry / "index.md"
    # Bytes, not text: a message body keeps its own line ends.
    text = index.read_bytes().decode("utf8")
    head, fence, _ = text.partition("\n---")
    if not text.startswith("---\n") or not fence or STAMPED.search(head):
        return 0
    when = sent_at((entry / RAW_NAME).read_bytes())
    if not when:
        return 0
    new = f'---\naangemaakt: "{when}" # {HINT}\n{text[4:]}'
    if apply:
        index.write_bytes(new.encode("utf8"))
        print(f"  stamp {index}")
    else:
        print(f"  [dry] stamp {index}")
    return 1


def stamp(config: Path, apply: bool) -> int:
    text = config.read_text(encoding="utf8")
    new = VERSION_RE.sub("version: 12", text)
    if new == text:
        return 0
    if apply:
        config.write_text(new, encoding="utf8")
        print(f"  version 12 {config}")
    else:
        print(f"  [dry] version 12 {config}")
    return 1


def main(data_dir: Path, apply: bool) -> int:
    config = data_dir / ".app" / "config.yaml"
    if not config.is_file():
        sys.exit(f"ERROR: {config} not found. Is {data_dir} an ODAS data dir?")

    found = mail_entries(data_dir)
    print(f"Data dir: {data_dir}  ({len(found)} mail entries)\n")
    changed = stamp(config, apply) + sum(stamp_entry(e, apply) for e in found)

    print(f"\n{changed} file(s) {'changed' if apply else 'to change'}.")
    if not apply and changed:
        print("Dry run — pass --apply to write.")
    return changed
