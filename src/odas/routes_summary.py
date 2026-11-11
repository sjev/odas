"""Asking for the summary of one document.

Two routes on the address the attachment link already uses. The POST comes back
at once and the reading runs behind it; the GET is what the page polls while it
waits. Neither one calls a model: that is `ai.py`, through `summary_jobs.py`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from odas import ai, documents, summary_jobs, zaak
from odas.web_helpers import get_by, require_team, zaak_folder

router = APIRouter()

ADDRESS = "/zaken/{ref}/log/{entry_name}/bijlage/{filename}/samenvatting"


def _one_document(folder: Path, entry_name: str, filename: str) -> documents.Document:
    """The row this address names. The entry is part of it, so a repeated
    filename in another entry is a different document, never this one."""
    for row in documents.documents_of(folder, zaak.load(folder)):
        if row.entry == entry_name and row.name == filename:
            return row
    raise HTTPException(status_code=404, detail="document niet gevonden")


@router.post(ADDRESS, tags=["ui"])
async def summary_start(request: Request, ref: str, entry_name: str, filename: str) -> Response:
    """Ask the model to read one document. Comes back at once; the work runs behind it."""
    folder = zaak_folder(request, ref)
    require_team(request)
    if not ai.configured():
        raise HTTPException(status_code=404, detail="deze data dir vraagt geen samenvattingen")
    row = _one_document(folder, entry_name, filename)
    summary_jobs.forget(row.key)  # a press clears the last failure before trying again
    if not row.summary:
        summary_jobs.start(row.path, row.key, by=get_by(request))
    return RedirectResponse(f"/zaken/{ref}", status_code=303)


@router.get(ADDRESS, tags=["ui"])
async def summary_state(request: Request, ref: str, entry_name: str, filename: str) -> Response:
    """What this document's summary is doing, for the page that is waiting on it."""
    folder = zaak_folder(request, ref)
    require_team(request)
    row = _one_document(folder, entry_name, filename)
    status = "bezig" if row.bezig else "mislukt" if row.fout else "klaar" if row.summary else "leeg"
    return JSONResponse({"status": status, "samenvatting": row.summary, "fout": row.fout})
