"""`odas index`: the text and the summaries of the documents of the zaken.

Three verbs about the text of a document, and all three are free. `sync` gives
every document the text beside it, so it only backfills what the app did not
already do. `list` says what the folders hold. `text` prints what was extracted.
Nothing here calls a model: the two verbs that can are in `cli_summaries.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from odas.documents import Document

app = typer.Typer(
    help="The documents of the zaken: their extracted text, and their summaries.",
    no_args_is_help=True,
)


def _folders(ref: str | None) -> list[tuple[str, Path]]:
    """The zaken to work on: the one named, or the whole data dir."""
    from odas import zaak

    if ref:
        folder = zaak.find(ref)
        if folder is None:
            raise typer.BadParameter(f"unknown zaak: {ref}")
        return [(ref, folder)]
    return [(zaak.load_safe(f).ref, f) for f in zaak.list_folders()]


def _documents(ref: str | None) -> list[tuple[str, Document]]:
    """Every document of the zaken named, each with the ref it belongs to."""
    from odas import documents, zaak

    return [
        (name, d)
        for name, folder in _folders(ref)
        for d in documents.documents_of(folder, zaak.load(folder))
    ]


@app.command()
def sync(
    ref: str | None = typer.Argument(None, help="One zaak; omit to sweep them all"),
    force: bool = typer.Option(
        False, "--force", help="Read every document again, not just new ones."
    ),
) -> None:
    """Make the derived data match the folders. A new document syncs itself when filed."""
    import logging
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor, as_completed

    from odas import documents
    from odas.progress import Progress

    folders = _folders(ref)
    jobs = [(name, path) for name, folder in folders for path in documents.files_of(folder)]
    doc_log = logging.getLogger("odas.documents")
    null_handler = logging.NullHandler()  # a log.warning here must not also print raw
    doc_log.addHandler(null_handler)

    # spawn, not fork: this process may already be multi-threaded (e.g. under a test client)
    ctx = multiprocessing.get_context("spawn")
    warnings = 0
    try:
        with Progress(total=len(jobs)) as progress, ProcessPoolExecutor(mp_context=ctx) as pool:
            futures = {
                pool.submit(documents.extract_one_safe, path, force): (name, path)
                for name, path in jobs
            }
            for future in as_completed(futures):
                name, path = futures[future]
                _, warning, error = future.result()
                progress.update(f"{name}/{path.name}")
                if error:
                    doc_log.warning(f"Document could not be read: path={str(path)!r} error={error}")
                elif warning:
                    doc_log.warning(f"Document has no text layer: path={str(path)!r}")
                    progress.warn(f"{name}  {warning}")
                    warnings += 1
    finally:
        doc_log.removeHandler(null_handler)

    rows = _documents(ref)
    pages = sum(d.pages for _, d in rows)
    typer.echo(f"{len(rows)} documents, {pages} pages, {warnings} warnings")


@app.command("list")
def list_(ref: str | None = typer.Argument(None, help="One zaak; omit to list them all")) -> None:
    """Print what the store holds: one row per document, with its pages and its summary."""
    from odas import documents

    typer.echo(f"{'zaak':<10}{'document':<36}{'pages':>6}  {'summary':<8}state")
    for name, d in _documents(ref):
        state = documents.NO_TEXT if d.warn else ""
        pages = "-" if d.warn or not d.pages else str(d.pages)
        typer.echo(f"{name:<10}{d.name:<36}{pages:>6}  {'yes' if d.summary else '-':<8}{state}")


def _one(ref: str, name: str) -> Document:
    """The document of this zaak that carries this name."""
    rows = [d for _, d in _documents(ref) if d.name == name]
    if not rows:
        raise typer.BadParameter(f"no such document in {ref}: {name}")
    return rows[0]


@app.command()
def text(
    ref: str = typer.Argument(..., help="The zaak to read"),
    name: str = typer.Argument("", help="One document; omit for all that need a summary"),
) -> None:
    """Print the extracted text. This reads; it never writes and never calls a model."""
    from odas import documents, index

    rows = [_one(ref, name)] if name else [d for _, d in _documents(ref) if not d.summary]
    for d in rows:
        typer.echo(f"\n# {d.name} ({d.entry})")
        typer.echo(index.text_of(d.path, d.key) or f"({documents.NO_TEXT})")
