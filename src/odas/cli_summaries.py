"""`odas index summarize` and `odas index summary`: the prose about a document.

These are the two verbs that touch a summary. `summarize` is the one that costs
money -- it hands the documents you name to the model. `summary` only reads back
what is stored, or takes prose a person wrote themselves.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from odas.cli_documents import _documents, _one, app


@app.command()
def summarize(
    ref: str = typer.Argument(..., help="The zaak to read"),
    name: str = typer.Argument("", help="One document; omit for all that need a summary"),
    force: bool = typer.Option(False, "--force", help="Read a document again, summary or not."),
) -> None:
    """Have the model summarize documents. Costs tokens: it reads what you name."""
    import logging

    from odas import ai, summary_jobs

    if not ai.configured():
        raise typer.BadParameter("no ai section in .app/config.yaml: nothing to summarize with")
    # This command prints its own reason per document; a log.warning must not also print raw.
    logging.getLogger("odas").addHandler(logging.NullHandler())
    rows = [_one(ref, name)] if name else [d for _, d in _documents(ref) if not d.summary]
    for d in rows:
        if d.summary and not force:
            typer.echo(f"skipped (has a summary): {d.name}")
            continue
        try:
            summary_jobs.write_one(d.path, d.key, by="cli")
        except ValueError as e:
            typer.echo(f"skipped: {d.name}: {e}")
            continue
        typer.echo(f"summary stored: {d.name}")


@app.command()
def summary(
    ref: str = typer.Argument(..., help="The zaak the document belongs to"),
    name: str = typer.Argument(..., help="The document"),
    set_: str = typer.Option("", "--set", help="Store a summary: '-' reads stdin, else a path"),
) -> None:
    """Print the summary of one document, or store one a person wrote themselves."""
    from odas import index

    d = _one(ref, name)
    if not set_:
        typer.echo(index.summary_of(d.path, d.key) or "")
        return
    written = sys.stdin.read() if set_ == "-" else Path(set_).read_text(encoding="utf8")
    index.write_summary(d.path, d.key, written, by="agent")
    typer.echo(f"summary stored: {name}")
