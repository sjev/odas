"""The public intake form, built from the type that declares `public_intake`.

The route holds no field list. It asks the config which type owns the public
form, renders that type's public fields, and writes back exactly those. Three
things are structural rather than declared, because every intake has them: a
`titel`, an `omschrijving` that becomes the zaak body, and attachments.

A data dir may ship its own page as `.app/intake.html`. It is served as it is,
and it posts one JSON part, `zaak`: `{"titel", "body", "velden"}`. The server
reads that part with the same rules, and answers in JSON.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile  # what request.form() actually yields

from odas import audit, intake_guard, log_write, mail, zaak, zaak_create
from odas.appconfig import Field, intake_type, mailin_address, public_fields
from odas.config import Config
from odas.intake_answers import OMSCHRIJVING, TITEL, TITEL_MAX, check, email_key, from_json
from odas.templating import templates
from odas.web_helpers import read_uploads

log = logging.getLogger(__name__)
router = APIRouter()
NOT_CONFIRMED = "Er ging geen bevestiging per e-mail uit. Bewaar uw kenmerk en de link hieronder."


def _fields() -> dict[str, Field]:
    return public_fields(intake_type())


def _render(
    request: Request, values: dict[str, str], errors: dict[str, str], status: int = 200
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="intake.html",
        context={"values": values, "errors": errors, "fields": _fields(), "titel_max": TITEL_MAX},
        status_code=status,
    )


def _own_form() -> Path:
    return Config().data_dir / "intake.html"


@router.get("/", tags=["ui"])
@router.get("/indienen", tags=["ui"])
async def intake_form(request: Request) -> Response:
    if _own_form().is_file():
        return HTMLResponse(_own_form().read_text(encoding="utf8"))
    return _render(request, {}, {})


@router.post("/indienen", tags=["ui"])
async def intake_submit(request: Request) -> Response:
    fields = _fields()
    form = await request.form()
    own = form.get("zaak")
    try:
        # A data dir's own page sends its answers as JSON; the builtin form as fields.
        answers = from_json(own) if isinstance(own, str) else form
    except ValueError as e:
        return JSONResponse({"errors": {"_": str(e)}}, status_code=422)

    # Iterate the declared fields, never the submitted keys: an injected key is
    # never read, and a field owning several disk keys contributes all of them.
    values = {
        k: str(answers.get(k, "")).strip() for key, f in fields.items() for k in f.disk_keys(key)
    }
    values[TITEL] = str(answers.get(TITEL, "")).strip()
    values[OMSCHRIJVING] = str(answers.get(OMSCHRIJVING, "")).strip()

    uploads = [f for f in form.getlist("documenten") if isinstance(f, UploadFile) and f.filename]
    docs, doc_error = await read_uploads(uploads)
    doc_error = doc_error or intake_guard.bad_file(docs)
    errors = check(values, fields) | ({"documenten": doc_error} if doc_error else {})
    guard = [str(form.get(k, "")) for k in (intake_guard.HONEYPOT, intake_guard.ELAPSED)]
    if intake_guard.is_bot(*guard):
        log.info("Intake refused: honeypot filled or form sent too fast")
        errors = {"_": intake_guard.REFUSED}

    if errors:
        if isinstance(own, str):
            return JSONResponse({"errors": errors}, status_code=422)
        return _render(request, values, errors, status=422)

    new_zaak = zaak_create.create_zaak(
        {k: v for k, v in values.items() if k not in (TITEL, OMSCHRIJVING)},
        titel=values[TITEL],
        body=values[OMSCHRIJVING],
        documents=docs,
    )
    base = str(request.base_url).rstrip("/")
    done = {
        "ref": new_zaak.ref,
        "adres": mailin_address(new_zaak.ref),
        "inzien_url": f"{base}/inzien-{new_zaak.token}" if new_zaak.token else "",
    }
    sent = await _confirm(new_zaak, values.get(email_key(fields), ""), done["inzien_url"])
    done["melding"] = "" if sent else NOT_CONFIRMED  # a relay's reason is not for the public
    if isinstance(own, str):
        return JSONResponse(done)
    return templates.TemplateResponse(request=request, name="confirmation.html", context=done)


async def _confirm(new_zaak: zaak.Zaak, to: str, inzien_url: str) -> bool:
    """Mail the indiener their inzien link, and note the outcome on the indiening.

    That link is the only way they reach their zaak, so a confirmation that
    stayed is noted with its reason. The team then sends the link by hand. The
    note goes on the IN entry, so the indiening shows the whole outcome.
    """
    folder = zaak.find(new_zaak.ref)
    if folder is None:  # the zaak was just written; only a disk fault gets here
        return True
    if not intake_guard.may_mail(to):
        _note(folder, f"Bevestiging niet verstuurd naar {to}: daglimiet bereikt.")
        return False
    try:
        msg = await run_in_threadpool(
            mail.send_template,
            mail.INTAKE_BEVESTIGING,
            [to],
            reply_to=mailin_address(new_zaak.ref),  # an answer lands on the zaak itself
            values={"ref": new_zaak.ref, "inzien_url": inzien_url},
        )
    except mail.MailError as e:
        _note(folder, f"Bevestiging niet verstuurd naar {to}: {e}")
        return False
    if msg is not None:
        # The audit line too, not a UIT entry: a message the app sends by itself
        # must not look like the team's answer to the indiener.
        audit.write(folder, f"bevestiging verstuurd naar {to}", by="systeem")
        _note(folder, f"Bevestiging verstuurd naar {to}.")
    return True


def _note(folder: Path, line: str) -> None:
    """Append one line to the body of the indiening, the zaak's first entry."""
    name = zaak.load(folder).log_entries[0].name
    raw = log_write.read_log_entry_raw(folder, name) or ""
    log_write.update_log_entry(folder, name, f"{raw.rstrip()}\n\n{line}\n")
