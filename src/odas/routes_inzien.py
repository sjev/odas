"""Public indiener pages: reply-token view, reply POST, own-fields editor."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from odas import audit, documents, index_write, log_files, log_write, schema, zaak
from odas.appconfig import public_fields
from odas.templating import templates
from odas.web_helpers import read_uploads, token_folder
from odas.zaak_view import public_view, zaak_context

router = APIRouter()


def _indiener_fields(folder: Path) -> dict[str, schema.Field]:
    """The fields the indiener may edit. One rule, shared with the intake form."""
    return public_fields(zaak.load_safe(folder).soort)


@router.get("/inzien-{token}", tags=["public"])
async def inzien(request: Request, token: str, sent: str = "") -> Response:
    folder = token_folder(token)
    ctx = zaak_context(request, folder, public=True, values={}, errors={}, sent=bool(sent))
    return templates.TemplateResponse(request=request, name="zaak.html", context=ctx)


@router.post("/inzien-{token}", tags=["public"])
async def reply_submit(
    request: Request,
    token: str,
    naam: str = Form(""),
    onderwerp: str = Form(""),
    bericht: str = Form(""),
    documenten: list[UploadFile] = File(default=[]),
) -> Response:
    folder = token_folder(token)
    values = {"naam": naam.strip(), "onderwerp": onderwerp.strip(), "bericht": bericht.strip()}
    errors = {
        f: "Dit veld is verplicht." for f in ("naam", "onderwerp", "bericht") if not values[f]
    }
    docs, doc_error = await read_uploads([f for f in documenten if f.filename])
    if doc_error:
        errors["documenten"] = doc_error

    if errors:
        ctx = zaak_context(request, folder, public=True, values=values, errors=errors, sent=False)
        return templates.TemplateResponse(
            request=request, name="zaak.html", context=ctx, status_code=422
        )

    by = values["naam"] or "indiener"
    log_write.write_log_entry(
        folder,
        "IN",
        values["onderwerp"],
        values["bericht"],
        attachments=docs,
        by=by,
    )
    audit.write(folder, f"reactie ontvangen: {values['onderwerp']}", by=by)
    return RedirectResponse(f"/inzien-{token}?sent=1#success-banner", status_code=303)


@router.get("/inzien-{token}/log/{entry_name}/bijlage/{filename}", tags=["public"])
async def inzien_attachment(token: str, entry_name: str, filename: str) -> Response:
    """A document of a log item the indiener can see.

    `public_view` is the one rule for which items reach them, so an internal
    note is no more fetchable here than it is readable there. The message
    itself is not a document, and stays with the team.
    """
    folder = token_folder(token)
    stem = entry_name.removesuffix(".md")
    entries = public_view(zaak.load(folder)).log_entries
    if filename in documents.SKIP or not any(e.name == stem for e in entries):
        raise HTTPException(status_code=404, detail="bijlage niet gevonden")
    return log_files.serve(folder, stem, filename)


@router.get("/inzien-{token}/bewerken", tags=["public"])
async def inzien_edit_form(request: Request, token: str) -> Response:
    folder = token_folder(token)
    fields = _indiener_fields(folder)
    if not fields:
        raise HTTPException(status_code=404, detail="pagina niet gevonden")
    ctx = {"zaak": zaak.load(folder), "token": token, "error": None, "fields": fields}
    return templates.TemplateResponse(request=request, name="inzien_bewerken.html", context=ctx)


@router.post("/inzien-{token}/bewerken", tags=["public"])
async def inzien_edit(request: Request, token: str) -> Response:
    """Indiener edits a small whitelist of fields; other fields stay untouched."""
    folder = token_folder(token)
    fields = _indiener_fields(folder)
    if not fields:
        raise HTTPException(status_code=404, detail="pagina niet gevonden")
    form = await request.form()
    # Iterate the fields the role may edit, not the submitted keys: an injected
    # key is never read. A field owning several disk keys contributes all of them.
    updates = {k: str(form.get(k, "")) for key, f in fields.items() for k in f.disk_keys(key)}
    try:
        index_write.update_fields(folder, updates, by="indiener")
    except ValueError as e:
        z = zaak.load(folder)
        z.frontmatter.update(updates)  # keep the indiener's submitted values on the form
        ctx = {"zaak": z, "token": token, "error": str(e), "fields": fields}
        return templates.TemplateResponse(
            request=request, name="inzien_bewerken.html", context=ctx, status_code=422
        )
    return RedirectResponse(f"/inzien-{token}", status_code=303)
