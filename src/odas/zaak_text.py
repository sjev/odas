"""A zaak as one Markdown text, for a person to paste into an AI tool.

The reader is a language model that knows nothing of ODAS. So the text opens
with a reading key, says who sent and who received each log entry, and drops
what only the app needs: YAML comments, empty fields, flags, coordinates and
the access list. It carries words only; an attachment brings its name and, if
one was made, its summary. The zip is the raw copy.
"""

from __future__ import annotations

import re
from pathlib import Path

from odas import appconfig, clock, documents, zaak
from odas.fields.base import Field
from odas.fields.flag import FlagField
from odas.fields.latlon import LatLonField
from odas.fields.toegang import ToegangField

# The heading names the case, and the rest is for the app, not about the case.
SKIP_KEYS = {"id", "titel"}
SKIP_KINDS = (FlagField, LatLonField, ToegangField)
HEADING = re.compile(r"^(#{1,6}) ", re.MULTILINE)


def _demote(text: str, levels: int) -> str:
    """Push headings down, so text a person wrote never outranks the export's own."""
    return HEADING.sub(lambda m: "#" * min(len(m[1]) + levels, 6) + " ", text)


def _shown(f: Field, key: str, fm: dict[str, str]) -> str:
    values = [str(fm.get(k) or "").strip() for k in f.disk_keys(key)]
    labels = {o.value: o.label for o in f.options if o.label}
    return " ".join(labels.get(v, v) for v in values if v)


def _gegevens(z: zaak.Zaak) -> str:
    rows = [f"- Soort: {appconfig.type_label(z.soort)}"]
    for key, f in z.fields.items():
        if key in SKIP_KEYS or key == "soort" or isinstance(f, SKIP_KINDS):
            continue
        value = _shown(f, key, z.frontmatter)
        if value:
            rows.append(f"- {f.label}: {value}")
    return "\n".join(rows)


def _entry(entry: zaak.LogEntry, docs: list[documents.Document]) -> str:
    title = entry.frontmatter.get("onderwerp") or entry.slug.replace("-", " ")
    moment = f"{entry.datum} {entry.time}".strip()
    lines = [f"### {moment} · {entry.direction} · {title}", ""]
    people = [
        f"{f.label}: {_shown(f, key, entry.frontmatter)}"
        for key, f in appconfig.log_fields().items()
        if f.type in ("email", "list[email]") and _shown(f, key, entry.frontmatter)
    ]
    if people:
        lines += [" · ".join(people), ""]
    if entry.body.strip():
        lines += [_demote(entry.body.strip(), 3), ""]
    for d in docs:
        lines.append(f"Bijlage: {d.name}")
        if d.summary:
            lines += ["Samenvatting van de bijlage:", d.summary.strip()]
        lines.append("")
    return "\n".join(lines)


def render(folder: Path) -> str:
    """The case text: reading key, then Gegevens, Samenvatting and Logboek."""
    z = zaak.load(folder)
    org = appconfig.org().display_name
    by_entry = documents.by_entry(documents.documents_of(folder, z))
    entries = [_entry(e, by_entry.get(e.name, [])) for e in z.log_entries]
    return (
        "\n".join(
            [
                f"# Zaak {z.ref}: {z.titel}",
                "",
                f"Export uit ODAS van {org}, {clock.now():%Y-%m-%d}.",
                "Opbouw: 1. Gegevens, 2. Samenvatting, 3. Logboek van oud naar nieuw.",
                f"Richting in het logboek: IN = ontvangen door {org}, "
                f"UIT = verstuurd door {org}, LOG = interne notitie van {org}.",
                "Van een bijlage staan alleen de naam en, als die er is, een samenvatting in deze tekst.",
                "",
                "## 1. Gegevens",
                "",
                _gegevens(z),
                "",
                "## 2. Samenvatting",
                "",
                _demote(z.body.strip(), 1) or "Geen samenvatting.",
                "",
                f"## 3. Logboek ({len(entries)} items)",
                "",
                *(entries or ["Geen items.", ""]),
            ]
        ).rstrip()
        + "\n"
    )
