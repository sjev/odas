"""The index.md editor: the context its page needs, and the POST that saves it.

Two ways in, one save. Raw mode replaces the whole file; field mode reads every
key the role may not edit back from disk, so a tampered input changes nothing.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from odas import access, index_write, schema, zaak
from odas.fields import ToegangField, declared_key
from odas.templating import templates
from odas.zaak_view import edit_context

TEMPLATE = "zaak_bewerken.html"


def context(
    folder: Path,
    ref: str,
    fm: dict[str, str],
    body: str,
    raw: str,
    reopen_raw: bool,
    error: str | None,
    v: access.Viewer,
) -> dict[str, object]:
    """Everything the editor page draws.

    The values are put on the zaak first, so the dropdowns show what was just
    submitted rather than what is still on disk.
    """
    z = zaak.load_safe(folder)
    z.frontmatter.update(fm)
    return {
        "ref": ref,
        "fm": fm,
        "body": body,
        "raw": raw,
        "reopen_raw": reopen_raw,
        "error": error,
        "fields": z.fields,
        **edit_context(z, v),
    }


def form_context(folder: Path, ref: str, v: access.Viewer) -> dict[str, object]:
    """Context for the GET editor form, read from the file as it stands."""
    raw = (folder / "index.md").read_text(encoding="utf8")
    fm, body, reopen_raw = schema.parse_or_raw(raw)
    error = "Ongeldige frontmatter." if reopen_raw else None
    return context(folder, ref, fm, body, raw, reopen_raw, error, v)


async def handle_edit_submit(request: Request, folder: Path, ref: str, by: str) -> Response:
    """Handle the POST for both raw-text and form-field edit modes."""
    form = await request.form()
    viewer = access.of(request)
    before = zaak.load_safe(folder)

    def refused(fm: dict[str, str], body: str, raw: str, reopen_raw: bool, error: str) -> Response:
        return templates.TemplateResponse(
            request=request,
            name=TEMPLATE,
            context=context(folder, ref, fm, body, raw, reopen_raw, error, viewer),
            status_code=422,
        )

    if str(form.get("mode", "")) == "raw":
        raw_content = str(form.get("raw_content", ""))
        try:
            _refuse_unopenable(viewer, before, schema.parse_or_raw(raw_content)[0])
            index_write.update_index(folder, raw_content, by)
        except ValueError as e:
            # parse_or_raw, never parse: the text is refused *because* it may be
            # unreadable, so reading it again is what turned an error into a 500.
            fm, body, _ = schema.parse_or_raw(raw_content)
            return refused(fm, body, raw_content, True, str(e))
        return RedirectResponse(f"/zaken/{ref}", status_code=303)

    # Allowlist-shaped: a field this role may not edit is read back from disk, so
    # a tampered or missing hidden input can never change it.
    z = before
    fields = z.fields
    fm = schema.undeclared(z.frontmatter, fields)  # a key a schema change left behind stays
    fm.update(
        {
            k: str(form.get(k, "")) if "team" in f.editable else z.frontmatter.get(k, "")
            for key, f in fields.items()
            for k in f.disk_keys(key)
        }
    )
    # The access dialog posts one checkbox per grantee, under the key this soort
    # declares for the kind, so those values are joined into the one field.
    if grant := declared_key(fields, ToegangField):
        fm[grant] = ", ".join(str(v) for v in form.getlist(grant))
    body = str(form.get("body", ""))
    try:
        _refuse_unopenable(viewer, before, fm)
        index_write.update_index(folder, schema.dump(fm, body, fields), by)
    except ValueError as e:
        raw = (folder / "index.md").read_text(encoding="utf8")
        return refused(fm, body, raw, False, str(e))
    return RedirectResponse(f"/zaken/{ref}", status_code=303)


def _refuse_unopenable(v: access.Viewer, before: zaak.Zaak, after: dict[str, str]) -> None:
    """Refuse a new member the viewer may not open, in the words for an absent one."""
    if ref := access.unopenable_member(v, before, after):
        raise ValueError(f"Onbekende zaak: {ref}.")
