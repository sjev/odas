"""Zaak log-entry routes: the URLs and the auth; the flow is in log_handlers."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse, Response

from odas import log_files, log_handlers, log_write, mail_source, mailin_store, trash, zaak
from odas.templating import templates
from odas.web_helpers import get_by, log_values, zaak_folder

router = APIRouter()


def _entry_or_404(folder: Path, entry_name: str) -> zaak.LogEntry:
    entry = log_handlers.find_entry(folder, entry_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="log-item niet gevonden")
    return entry


@router.post("/zaken/{ref}/log", tags=["ui"])
async def log_create(
    request: Request,
    ref: str,
    direction: str = Form("LOG"),
    entry_date: str = Form(""),
    body: str = Form(""),
    action: str = Form(""),  # "send" = the Verstuur e-mail button
    documenten: list[UploadFile] = File(default=[]),
) -> Response:
    folder = zaak_folder(request, ref)
    return await log_handlers.handle_log_create(
        request,
        folder,
        ref,
        direction=direction,
        entry_date=entry_date,
        velden=await log_values(request),
        body=body,
        documenten=documenten,
        by=get_by(request),
        send=action == "send",
    )


@router.get("/zaken/{ref}/log/{entry_name}/bewerken", tags=["ui"])
async def log_edit_form(request: Request, ref: str, entry_name: str) -> Response:
    folder = zaak_folder(request, ref)
    raw = log_write.read_log_entry_raw(folder, entry_name)
    if raw is None:
        raise HTTPException(status_code=404, detail="log-item niet gevonden")
    return templates.TemplateResponse(
        request=request,
        name=log_handlers.TEMPLATE,
        context=log_handlers.log_edit_context(folder, ref, entry_name, raw, error=None),
    )


@router.get("/zaken/{ref}/log/{entry_name}/verwijderen", tags=["ui"])
async def log_delete_form(request: Request, ref: str, entry_name: str) -> Response:
    """The one confirm step: what goes, how much of it, and where it lands."""
    folder = zaak_folder(request, ref)
    entry = _entry_or_404(folder, entry_name)
    return templates.TemplateResponse(
        request=request,
        name="verwijderen.html",
        context={
            "ref": ref,
            "kop": "Logboek-item verwijderen",
            "wat": entry.frontmatter.get("onderwerp") or entry.name,
            "aantal": len(entry.attachments),
            "action_url": f"/zaken/{ref}/log/{entry_name}/verwijderen",
            "cancel_url": f"/zaken/{ref}/log/{entry_name}/bewerken",
        },
    )


@router.post("/zaken/{ref}/log/{entry_name}/verwijderen", tags=["ui"])
async def log_delete(request: Request, ref: str, entry_name: str) -> Response:
    folder = zaak_folder(request, ref)
    by = get_by(request)
    entry = _entry_or_404(folder, entry_name)
    label = entry.frontmatter.get("onderwerp") or entry.name

    trash.trash_log_entry(folder, entry_name)
    log_handlers.audit_entry(folder, by, "verwijderd", entry.direction, label)
    return RedirectResponse(f"/zaken/{ref}", status_code=303)


@router.get("/zaken/{ref}/log/{entry_name}/bericht", tags=["ui"])
async def log_message(request: Request, ref: str, entry_name: str) -> Response:
    """The stored message as readable text: what the `.eml` window shows."""
    folder = zaak_folder(request, ref)
    path = log_files.entry_file(folder, entry_name, mailin_store.RAW_NAME)
    return PlainTextResponse(mail_source.readable(path.read_bytes()))


@router.get("/zaken/{ref}/log/{entry_name}/bijlage/{filename}", tags=["ui"])
async def log_attachment(request: Request, ref: str, entry_name: str, filename: str) -> Response:
    """Any file in the entry, including the received `bericht.eml`: the message is
    stored as an ordinary attachment, so it needs no route of its own."""
    return log_files.serve(zaak_folder(request, ref), entry_name, filename)


@router.post("/zaken/{ref}/log/{entry_name}/bewerken", tags=["ui"])
async def log_edit_submit(
    request: Request,
    ref: str,
    entry_name: str,
    body: str = Form(""),
    direction: str = Form(""),
    action: str = Form(""),  # "send" = the Verstuur e-mail button
    documenten: list[UploadFile] = File(default=[]),
    verwijder: list[str] = Form([]),
) -> Response:
    folder = zaak_folder(request, ref)
    return await log_handlers.handle_log_edit(
        request,
        folder,
        ref,
        entry_name,
        velden=await log_values(request),
        body=body,
        direction=direction,
        documenten=documenten,
        verwijder=verwijder,
        by=get_by(request),
        send=action == "send",
    )
