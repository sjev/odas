"""One file of one log entry: where it lies on disk, and how it is served.

Two pages address the same files: the team page under `/zaken/{ref}` and the
indiener page under `/inzien-{token}`. Who may ask is each route's business;
the path guard below is the same for both.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from odas import folder_store, mailin_store

# What a browser shows without running anything of ours. Anything else an
# indiener or a sender attached could be a page that runs as this site.
INLINE = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".txt"}


def entry_file(folder: Path, entry_name: str, filename: str) -> Path:
    """One file of one log entry, and nothing outside that entry's own folder."""
    stem = Path(entry_name).name.removesuffix(".md")
    entry_dir = (folder / "log" / stem).resolve()
    path = (entry_dir / Path(filename).name).resolve()
    if not path.is_relative_to(entry_dir) or not path.is_file():
        raise HTTPException(status_code=404, detail="bijlage niet gevonden")
    return path


def serve(folder: Path, entry_name: str, filename: str) -> FileResponse:
    """The file itself, inline so the browser previews it.

    Every entry keeps the message under one name, so the name to save it under
    is made here: the zaak and the entry, which no second message shares.
    """
    path = entry_file(folder, entry_name, filename)
    name = path.name
    if name == mailin_store.RAW_NAME:
        stem = Path(entry_name).name.removesuffix(".md")
        name = f"{folder_store.ref_from_folder(folder)}-{stem}.eml"
    if path.suffix.lower() in INLINE:
        headers = {"X-Content-Type-Options": "nosniff"}
        return FileResponse(path, filename=name, content_disposition_type="inline", headers=headers)
    # A sandboxed PDF does not render in Chrome, so only the downloads carry it.
    headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}
    return FileResponse(path, filename=name, content_disposition_type="attachment", headers=headers)
