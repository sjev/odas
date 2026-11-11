"""Layout 7 → 8: the text of a document moves out of the cache and beside it.

The text was kept under `.app/cache/text/<hash>.md`, which read a document once
however many zaken filed it. It cost every reader outside the app the ability to
find the words: no `grep` over `zaken/` reaches a folder named after a hash. This
script writes each cached text beside the document it came from, as
`<document>.tekst.md`, so one tree holds the case and every word in it.

It matches on content, exactly as layout 7 did for summaries: every document
under `zaken/` and `prullenbak/` is hashed, and a cache file whose name is that
hash becomes a sidecar. One document filed in three zaken gets three sidecars.
The hash moves from the file name into the frontmatter, so a sidecar still knows
which bytes it was read from.

A document whose text is missing is left alone. `odas index sync` reads it later,
which costs seconds and nothing else.

Nothing is deleted. `.app/cache/text/` stays where it is; a later
`rm -rf .app/cache` clears it once the sidecars are in place.

Stdlib only, so a migration keeps running against a data dir the app cannot load.
Dry run by default; pass `apply` to write. Idempotent: a second run reports zero
actions.
"""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

SUFFIX = ".tekst.md"
SIDECARS = (SUFFIX, ".samenvatting.md")
VERSION_RE = re.compile(r"^version:\s*7\b", re.MULTILINE)
# `key: value` inside a frontmatter block. The cache never wrote anything nested.
KEY_RE = re.compile(r"^([a-z_]+):[ \t]*(.*?)[ \t]*$", re.MULTILINE)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text.strip()
    parts = text.split("---", 2)
    if len(parts) != 3:
        return {}, text.strip()
    return dict(KEY_RE.findall(parts[1])), parts[2].strip()


def documents(data_dir: Path) -> list[Path]:
    """Every attachment of every zaak, deleted ones included: the text of a zaak in
    the prullenbak is worth as much as the zaak itself."""
    found: list[Path] = []
    for root in (data_dir / "zaken", data_dir / "prullenbak"):
        for entry_dir in sorted(root.glob("*/log/*")):
            if not entry_dir.is_dir():
                continue
            found += sorted(
                p
                for p in entry_dir.iterdir()
                if p.is_file() and p.name != "index.md" and not p.name.endswith(SIDECARS)
            )
    return found


def place(document: Path, cached: Path, apply: bool) -> int:
    """Write one sidecar beside its document, carrying the hash it was read from."""
    target = document.with_name(document.name + SUFFIX)
    # The name has to survive an atomic write, which adds `.tmp` on top of the
    # suffix. A filesystem that refuses it (ecryptfs caps a name at 143 bytes,
    # ext4 at 255) must not take the whole migration down with it.
    try:
        if target.is_file():
            return 0
        probe = target.with_name(target.name + ".tmp")
        probe.touch()
        probe.unlink()
    except OSError as e:
        print(f"  SKIP {document.name}: {e.strerror} for {target.name} ({len(target.name)} chars)")
        return 0
    fm, body = split_frontmatter(cached.read_text(encoding="utf8"))
    # An empty body is the mark of a document that was read and has no text layer.
    # It is worth moving: it is what tells a row "a scan" instead of "not read".
    pages = fm.get("pages") or str(body.count("\n## p") + (1 if body.startswith("## p") else 0))
    when = fm.get("extracted_at") or datetime.now(UTC).replace(microsecond=0).isoformat()
    head = f"document: {document.name}\nhash: {cached.stem}\npages: {pages}\nextracted_at: {when}\n"
    if apply:
        target.write_text(f"---\n{head}---\n\n{body}\n" if body else f"---\n{head}---\n", "utf8")
        print(f"  place {target}")
    else:
        print(f"  [dry] place {target}")
    return 1


def stamp(config: Path, apply: bool) -> int:
    text = config.read_text(encoding="utf8")
    new = VERSION_RE.sub("version: 8", text)
    if new == text:
        return 0
    if apply:
        config.write_text(new, encoding="utf8")
        print(f"  version 8 {config}")
    else:
        print(f"  [dry] version 8 {config}")
    return 1


def main(data_dir: Path, apply: bool) -> None:
    config = data_dir / ".app" / "config.yaml"
    if not config.is_file():
        sys.exit(f"ERROR: {config} not found. Is {data_dir} an ODAS data dir?")

    cache = data_dir / ".app" / "cache" / "text"
    cached = {p.stem: p for p in cache.glob("*.md")} if cache.is_dir() else {}
    found = documents(data_dir)
    print(f"Data dir: {data_dir}  ({len(found)} documents, {len(cached)} texts cached)\n")

    changed = stamp(config, apply)
    unread = 0
    for document in found:
        key = digest(document)
        if key in cached:
            changed += place(document, cached[key], apply)
        else:
            unread += 1

    print(f"\n{changed} file(s) {'changed' if apply else 'to change'}.")
    if unread:
        print(f"{unread} document(s) carry no cached text; `odas index sync` reads them.")
    print(f"{cache} is left alone; remove .app/cache once the sidecars look right.")
    if not apply and changed:
        print("Dry run — pass --apply to write.")
