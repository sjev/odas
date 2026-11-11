"""Zaak routes: list, detail view, export."""

from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from odas import (
    access,
    audit,
    folder_store,
    handleiding,
    log_reply,
    trash,
    zaak,
    zaak_columns,
    zaak_create,
    zaak_query,
)
from odas.appconfig import all_types, default_type_name, type_label
from odas.templating import templates
from odas.web_helpers import get_by, require_team, zaak_folder
from odas.zaak_view import zaak_context

router = APIRouter()


@router.get("/", tags=["ui"])
async def root() -> Response:
    """With no public form, the site opens on the list. The intake router shadows this."""
    return RedirectResponse("/zaken", status_code=303)


@router.get("/zaken", tags=["ui"])
async def index(request: Request) -> Response:
    soort = request.query_params.get("soort", "")
    status = request.query_params.get("status", "")
    q = request.query_params.get("q", "")
    sort = request.query_params.get("sort", "")
    # One folder scan feeds both the rows and the counts, so the counts follow the box.
    accessible = zaak_query.visible(access.of(request))
    found = zaak_query.narrow(accessible, q=q, status=status, sort=sort)
    # Whether the soort choice is offered at all is a structural fact, not one
    # the current narrowing may flip: it never depends on q or status.
    has_soort_choice = len(zaak_query.soort_counts(accessible, chosen=soort)) > 1
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "zaken": zaak_query.of_soort(found, soort),
            "soort_counts": zaak_query.soort_counts(found, chosen=soort),
            "has_soort_choice": has_soort_choice,
            "status_options": zaak_query.status_options(),
            "cols": zaak_columns.chosen(request.cookies.get(zaak_columns.COOKIE, "")),
            "candidates": zaak_columns.candidates(),
            "links": zaak_columns.headers({"soort": soort, "status": status, "q": q}, sort),
            "back": f"/zaken?{request.url.query}" if request.url.query else "/zaken",
            "soorten": [(name, type_label(name)) for name in all_types()],
            "total": len(found),
            "soort": soort,
            "status": status,
            "q": q,
            "sort": sort,
            "zoek_help": handleiding.section("Zoeken"),
        },
    )


@router.post("/columns", tags=["ui"])
async def columns_pick(
    request: Request, columns: list[str] = Form([]), back: str = Form("/zaken")
) -> Response:
    """Keep the ticked columns in this browser, then show the same list again."""
    response = RedirectResponse(zaak_columns.same_site(back), status_code=303)
    zaak_columns.remember(response, columns, secure=request.url.scheme == "https")
    return response


@router.post("/zaken", tags=["ui"])
async def create_zaak_intern(
    request: Request, titel: str = Form(""), soort: str = Form("")
) -> Response:
    """Create a near-empty zaak from a titel and go to its page to refine it."""
    require_team(request)
    by = get_by(request)
    try:
        new_zaak = zaak_create.create_minimal(titel, soort or default_type_name(), by=by)
    except ValueError:
        return RedirectResponse("/zaken", status_code=303)
    return RedirectResponse(f"/zaken/{new_zaak.ref}", status_code=303)


@router.get("/zaken/", tags=["ui"])
async def zaken_redirect() -> Response:
    return RedirectResponse("/zaken", status_code=308)


@router.api_route("/dossiers/{path:path}", methods=["GET", "POST"], tags=["ui"])
async def dossiers_redirect(path: str) -> Response:
    """A dossier is a zaak. Old links -- including those in sent mail -- still resolve."""
    return RedirectResponse(f"/zaken/{path}" if path else "/zaken", status_code=308)


@router.get("/zaken/{zaak_id}/verwijderen", tags=["ui"])
async def zaak_delete_form(request: Request, zaak_id: str) -> Response:
    """The one confirm step: the title, the attachment count, and where it lands."""
    folder = zaak_folder(request, zaak_id)
    z = zaak.load(folder)
    return templates.TemplateResponse(
        request=request,
        name="verwijderen.html",
        context={
            "ref": zaak_id,
            "kop": "Zaak verwijderen",
            "wat": z.titel,
            "aantal": sum(len(e.attachments) for e in z.log_entries),
            "action_url": f"/zaken/{zaak_id}/verwijderen",
            "cancel_url": f"/zaken/{zaak_id}/bewerken",
        },
    )


@router.post("/zaken/{zaak_id}/verwijderen", tags=["ui"])
async def zaak_delete(request: Request, zaak_id: str) -> Response:
    folder = zaak_folder(request, zaak_id)
    # The line goes in before the move: what happened travels with the thing it
    # happened to, so the prullenbak holds case files and not loose folders.
    audit.write(folder, f"zaak verwijderd: {zaak.load(folder).titel}", by=get_by(request))
    trash.trash_zaak(folder)
    return RedirectResponse("/zaken", status_code=303)


@router.get("/zaken/{zaak_id}/export.zip", tags=["ui"])
async def zaak_export_zip(request: Request, zaak_id: str) -> StreamingResponse:
    folder = zaak_folder(request, zaak_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in folder.rglob("*"):
            rel = file.relative_to(folder).parts
            # An export is the case as it stands, never what was taken out of it,
            # and never the capability that opens it: an export leaves the building.
            if file.is_file() and trash.TRASH not in rel and folder_store.TOKEN_FILE not in rel:
                zf.write(file, file.relative_to(folder.parent))
    buf.seek(0)
    filename = f"{folder.name}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/zaken/{zaak_id}", tags=["ui"])
async def zaak_view(request: Request, zaak_id: str) -> Response:
    folder = zaak_folder(request, zaak_id)
    context = zaak_context(request, folder)
    name = request.query_params.get("reply")
    entry = next((e for e in zaak.scan_log(folder) if e.name == name), None)
    if entry:
        context |= {"log_fm": log_reply.reply_form(entry), "log_direction": "UIT"}
    return templates.TemplateResponse(request=request, name="zaak.html", context=context)
