"""Audit log: append timestamped action lines to each zaak's audit.log, and read
every zaak's back as one list.

The trail is written for a person, one line at a time, in the order things
happened. Reading is the same file parsed back: no index, no journal, no second
store. The prullenbak is part of the scan, because a deleted zaak's last line is
the only record that it ever went.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from odas import clock, folder_store, schema, zaak
from odas.config import Config
from odas.naming import write_text_atomic

# What `write` puts on disk: a date, a time to the minute, an actor, a sentence.
LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) \[([^\]]*)\] (.*)$")


@dataclass(frozen=True)
class Event:
    """One recorded action, and the zaak it happened to."""

    at: datetime
    by: str
    ref: str
    text: str
    deleted: bool  # its zaak now sits in the prullenbak, so there is nothing to open


def write(folder: Path, text: str, by: str) -> None:
    """Append one timestamped, human-readable line to audit.log (best-effort).

    A line in the trail is a change, so the record's `gewijzigd:` takes the same moment.
    """
    now = clock.now()  # the trail is text a person reads, so it is on their clock
    with (folder / zaak.AUDIT_FILE).open("a", encoding="utf8") as f:
        f.write(f"{now:%Y-%m-%d %H:%M} [{by}] {text}\n")
    _stamp(folder, now)


def _stamp(folder: Path, at: datetime) -> None:
    """Set `gewijzigd:` in index.md. A record the app cannot read keeps its text."""
    index = folder / "index.md"
    if not index.is_file():
        return
    try:
        z = zaak.load(folder)
    except yaml.YAMLError:
        return
    fm = {**z.frontmatter, "gewijzigd": clock.stamp(at)}
    write_text_atomic(index, schema.dump(fm, z.body, z.fields))


def _read(folder: Path, deleted: bool) -> list[Event]:
    """Every line of one zaak's trail. A line that is not a line is left out."""
    try:
        text = (folder / zaak.AUDIT_FILE).read_text(encoding="utf8")
    except OSError:
        return []  # a case file the app cannot open must not empty the page
    ref = folder_store.ref_from_folder(folder)
    events = []
    for line in text.splitlines():
        found = LINE.match(line)
        if found:
            at = datetime.strptime(found.group(1), "%Y-%m-%d %H:%M")
            events.append(Event(at, found.group(2), ref, found.group(3), deleted))
    return events


def recent(limit: int) -> list[Event]:
    """Every zaak's trail, joined and newest first, cut to `limit` lines."""
    config = Config()
    events = []
    for root, deleted in ((config.zaken_dir, False), (config.prullenbak_dir, True)):
        for folder in sorted(root.glob("*")) if root.is_dir() else []:
            if folder.is_dir():
                events += _read(folder, deleted)
    events.sort(key=lambda e: e.at, reverse=True)
    return events[:limit]
