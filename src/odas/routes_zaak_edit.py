"""Zaak index.md editor routes (team only): the flow itself is in edit_handlers."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from odas import access, edit_handlers, index_write, zaak
from odas.fields import ZakenField
from odas.templating import templates
from odas.web_helpers import get_by, zaak_folder

router = APIRouter()


@router.get("/zaken/{zaak_id}/bewerken", tags=["ui"])
async def zaak_edit_form(request: Request, zaak_id: str) -> Response:
    return templates.TemplateResponse(
        request=request,
        name=edit_handlers.TEMPLATE,
        context=edit_handlers.form_context(
            zaak_folder(request, zaak_id), zaak_id, access.of(request)
        ),
    )


@router.post("/zaken/{zaak_id}/bewerken", tags=["ui"])
async def zaak_edit_submit(request: Request, zaak_id: str) -> Response:
    folder = zaak_folder(request, zaak_id)
    return await edit_handlers.handle_edit_submit(request, folder, zaak_id, get_by(request))


@router.post("/zaken/{zaak_id}/flag", tags=["ui"])
async def zaak_flag(request: Request, zaak_id: str, flag: str = Form("")) -> Response:
    """The tick box on the zaak page. An unticked box posts nothing, so empty clears."""
    index_write.set_flag(zaak_folder(request, zaak_id), flag == "ja", get_by(request))
    return RedirectResponse(f"/zaken/{zaak_id}", status_code=303)


@router.post("/zaken/{zaak_id}/relatie/{key}", tags=["ui"])
async def zaak_relatie(
    request: Request, zaak_id: str, key: str, ref: str = Form(""), actie: str = Form("")
) -> Response:
    """Add or remove a member of a `zaken` field. The picker is the only writer."""
    folder = zaak_folder(request, zaak_id)
    z = zaak.load(folder)
    field = z.fields.get(key)
    if not isinstance(field, ZakenField):
        raise HTTPException(status_code=404, detail="Onbekende relatie.")

    current = z.frontmatter.get(key, "")
    error = None
    try:
        if actie == "verwijderen":
            updated = field.remove(current, ref)
        else:
            if not access.may_open(access.of(request), ref):
                raise ValueError(f"Onbekende zaak: {ref}.")  # ungranted reads as absent
            updated = field.add(current, ref)
        index_write.set_field(folder, key, updated, by=get_by(request))
    except ValueError as e:
        error = str(e)

    if error is None:
        return RedirectResponse(f"/zaken/{zaak_id}/bewerken", status_code=303)
    ctx = edit_handlers.form_context(folder, zaak_id, access.of(request))
    ctx["add_error"] = error
    ctx["add_value"] = ref
    return templates.TemplateResponse(
        request=request, name=edit_handlers.TEMPLATE, context=ctx, status_code=422
    )
