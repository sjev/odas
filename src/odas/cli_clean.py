"""`odas clean-log`: take the quoted chain out of the entries already on disk.

This is a backfill, not a daily tool. Mail that arrives now is shortened when it
is filed. This verb catches up the entries written before that rule existed.

It refuses any entry that has no `bericht.eml` beside it. Without that file there
is no second copy, so there is nothing to fall back on and nothing is cut.

The dry run prints the lines themselves, at the numbers they hold in `index.md`,
so a reader can check any of them with `sed -n` before anything is removed.
"""

from __future__ import annotations

from pathlib import Path

import typer

from odas import audit, log_write, quotes, schema, zaak
from odas.index_write import parse_raw
from odas.mailin_store import RAW_NAME

PREVIEW = 12  # lines of the cut shown per entry; --full shows every one


def _preview(index: Path, body: str, cut: int, full: bool) -> list[str]:
    """The lines about to go, numbered as `index.md` numbers them."""
    lines = body.splitlines()
    offset = len(index.read_text(encoding="utf8").splitlines()) - len(lines)
    shown = lines[cut:] if full else lines[cut : cut + PREVIEW]
    out = [f"  {offset + cut + i + 1:5d} | {line}" for i, line in enumerate(shown)]
    rest = len(lines) - cut - len(shown)
    return out + ([f"        | ... {rest} more lines"] if rest else [])


def _folders(ref: str) -> list[Path]:
    """The zaken in scope. No ref names them all, the way `odas list` does."""
    if not ref:
        return zaak.list_folders()
    folder = zaak.find(ref)
    if folder is None:
        raise typer.BadParameter(f"unknown zaak: {ref}")
    return [folder]


def clean_log(
    ref: str = typer.Argument("", help="The zaak to shorten. Leave it out for every zaak."),
    write: bool = typer.Option(False, "--write", help="Apply the cuts. Off is a dry run."),
    full: bool = typer.Option(False, "--full", help="Show every line, not the first few."),
) -> None:
    """Report the quoted message in every mail entry, and cut it on --write."""
    total = entries = 0
    for folder in _folders(ref):
        for entry in zaak.scan_log(folder):
            raw = log_write.read_log_entry_raw(folder, entry.name)
            if raw is None:
                continue
            fm, body = parse_raw(raw)
            cut = quotes.cut_at(body)
            if cut < 0:
                continue
            index = folder / "log" / entry.name / "index.md"
            here = zaak.load(folder).ref
            if not (index.parent / RAW_NAME).is_file():
                typer.echo(f"skipped, no {RAW_NAME}: {here}  log/{entry.name}")
                continue
            removed = len(body.splitlines()) - cut
            total, entries = total + removed, entries + 1
            typer.echo(f"\n{here}  log/{entry.name}  ({removed} lines)")
            if write:
                new_body = quotes.strip_quote(body)[0]
                content = schema.dump(fm, new_body, schema.log_fields())
                log_write.update_log_entry(folder, entry.name, content)
                audit.write(folder, f"citaat ingekort: {entry.name}", by="clean-log")
            else:
                typer.echo("\n".join(_preview(index, body, cut, full)))

    done = "removed" if write else "to remove"
    tail = "" if write else "  Use --write to remove them, --full to see every line."
    plural = "entry" if entries == 1 else "entries"
    typer.echo(f"\n{total} lines {done} in {entries} {plural}.{tail}")
