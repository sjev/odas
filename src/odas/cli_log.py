"""`odas log add`: file a log entry from a terminal.

It takes the same raw frontmatter and body the web editor takes, through the
same writer, and leaves the same audit line. So a note prepared elsewhere (by a
person or an agent) lands exactly as if it had been typed into the form.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

app = typer.Typer(help="Log entries of a zaak.", no_args_is_help=True)


@app.command("add")
def add(
    ref: str = typer.Argument(..., help="The zaak to file it in"),
    source: str = typer.Argument(..., help="A file of frontmatter and body; - reads stdin"),
    direction: str = typer.Option("LOG", "--direction", help="IN, UIT or LOG."),
    datum: str = typer.Option("", "--datum", help="JJJJ-MM-DD; today when left out."),
    by: str = typer.Option("cli", "--by", help="Who the audit trail names."),
) -> None:
    """File a log entry, and print the name it was filed under."""
    from datetime import date

    from odas import log_write, zaak
    from odas.index_write import parse_raw
    from odas.log_handlers import audit_entry

    folder = zaak.find(ref)
    if folder is None:
        raise typer.BadParameter(f"unknown zaak: {ref}")
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf8")
    direction = direction.upper()
    try:
        entry = log_write.create_log_entry(
            folder, direction, datum or date.today().isoformat(), raw, by=by
        )
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    onderwerp = parse_raw(raw)[0].get("onderwerp") or entry.name.removesuffix(".md")
    audit_entry(folder, by, "aangemaakt", direction, onderwerp)
    typer.echo(entry.name.removesuffix(".md"))  # the name `odas show` prints
