"""`odas list` and `odas show`: a case in a terminal.

Both verbs concatenate files in name order. They compute nothing, they cache
nothing and they reach no network, so what a reader sees here is what the folder
holds. A capability never leaves: the reply token opens a page and the toegang
list names people, and this output is meant to be piped anywhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from odas.fields import ToegangField, TokenField

if TYPE_CHECKING:
    from pathlib import Path

    from odas.zaak import LogEntry, Zaak

# What a reader may pipe into a mail, and so what never enters this output.
CAPABILITIES = (TokenField, ToegangField)
RULE = "-" * 72  # opens every entry, so a body heading never reads as one


def _values(values: dict[str, str], hidden: frozenset[str] = frozenset()) -> list[str]:
    """The frontmatter a reader wants: what is set, minus what is a capability."""
    return [f"{k}: {v}" for k, v in values.items() if v and k not in hidden]


def _hidden_keys(z: Zaak) -> frozenset[str]:
    """The fields of this soort that are capabilities, whatever the type calls them."""
    return frozenset(key for key, f in z.fields.items() if isinstance(f, CAPABILITIES))


def _tekst_state(path: Path, key: str) -> str:
    """What lies beside this document, for these bytes. A sidecar that names other
    bytes describes the document that was replaced, so it is named, never read."""
    from odas import documents, index

    text = index.text_of(path, key)
    if text is None:
        return "verouderd" if index.text_path(path).is_file() else "nee"
    return documents.NO_TEXT if not text else f"{index.pages_of(path, key)} blz"


def _samenvatting_state(path: Path, key: str) -> str:
    from odas import index

    if index.summary_of(path, key):
        return "ja"
    return "verouderd" if index.summary_path(path).is_file() else "nee"


def _attachment_lines(folder: Path, entry: LogEntry) -> list[str]:
    """One line per document: named, never described. The words themselves are a
    separate ask, because one case can hold hundreds of pages."""
    from odas import documents, index

    lines = []
    for rel in entry.attachments:
        path = folder / rel
        if path.name in documents.SKIP or not path.is_file():
            continue
        key = index.digest(path)
        lines.append(
            f"- {path.name} (tekst: {_tekst_state(path, key)}, "
            f"samenvatting: {_samenvatting_state(path, key)})"
        )
    return lines


def _positions(entries: list[LogEntry]) -> dict[str, str]:
    """Which of that date's entries each one is: name -> "3/5". A letterless legacy
    name has no place in the order, so it gets none."""
    per_date: dict[str, list[str]] = {}
    for e in entries:
        if e.letter:
            per_date.setdefault(e.datum, []).append(e.name)
    return {
        name: f"{i + 1}/{len(names)}" for names in per_date.values() for i, name in enumerate(names)
    }


def _heading(entry: LogEntry, position: str) -> str:
    """The name read back in words. The exact name follows on its own line."""
    parts = [entry.datum, position, entry.direction, entry.slug.replace("-", " ")]
    return " \u00b7 ".join(p for p in parts if p)


def _entry_block(folder: Path, entry: LogEntry, position: str, short: bool = False) -> list[str]:
    """A rule, the heading in words, then the name itself. A note body carries Dutch
    headings of its own, so an entry has to be tellable from a paragraph inside one."""
    body = "" if short else entry.body.strip()
    documents = _attachment_lines(folder, entry)
    return [
        "",
        RULE,
        f"## {_heading(entry, position)}",
        f"log/{entry.name}",
        *_values(entry.frontmatter),
        *(["", body] if body else []),
        *(["", "documenten:", *documents] if documents else []),
    ]


def show(
    ref: str = typer.Argument(..., help="The zaak to read"),
    limit: int = typer.Option(0, "--limit", help="Keep only the newest N log entries."),
    since: str = typer.Option("", "--since", help="Keep only entries from this date on."),
    direction: str = typer.Option("", "--direction", help="Keep only IN, UIT or LOG entries."),
    short: bool = typer.Option(False, "--short", help="Name the entries; leave their bodies out."),
    with_log: bool = typer.Option(True, "--log/--no-log", help="Include the log entries."),
) -> None:
    """Print the state of a zaak, then its log entries in the order their names carry."""
    from odas import zaak

    folder = zaak.find(ref)
    if folder is None:
        raise typer.BadParameter(f"unknown zaak: {ref}")
    z = zaak.load(folder)
    lines = [f"# {folder.name}", *_values(z.frontmatter, _hidden_keys(z)), "", z.body.strip()]
    entries = z.log_entries if with_log else []
    positions = _positions(entries)  # the day is counted whole, before any filter
    if since:
        entries = [e for e in entries if e.datum >= since]
    if direction:
        entries = [e for e in entries if e.direction == direction.upper()]
    for entry in entries[-limit:] if limit > 0 else entries:
        lines += _entry_block(folder, entry, positions.get(entry.name, ""), short)
    typer.echo("\n".join(lines))


def list_() -> None:
    """Print one row per zaak: what it is, where it stands, and what is due."""
    from odas import zaak

    typer.echo(f"{'ref':<10}{'soort':<12}{'status':<16}{'termijn':<12}{'log':>4}  titel")
    for z in zaak.list_all():
        termijn = z.termijn.due if z.termijn else "-"
        typer.echo(
            f"{z.ref:<10}{z.soort:<12}{(z.status or '-'):<16}"
            f"{termijn:<12}{len(z.log_entries):>4}  {z.titel}"
        )


def files(ref: str = typer.Argument(..., help="The zaak to read")) -> None:
    """Print the path of every document of a zaak. A dossier adds those of its zaken."""
    from odas import documents, zaak
    from odas.fields import ZakenField

    folder = zaak.find(ref)
    if folder is None:
        raise typer.BadParameter(f"unknown zaak: {ref}")
    z = zaak.load(folder)
    members = [
        r
        for key, f in z.fields.items()
        if isinstance(f, ZakenField)
        for r in f.refs(z.frontmatter.get(key, ""))
    ]
    folders = [folder]
    for r in members:
        member = zaak.find(r)
        if member is None:
            typer.echo(f"unknown zaak in dossier: {r}", err=True)
        else:
            folders.append(member)
    for f in folders:
        for path in documents.files_of(f):
            typer.echo(path)
