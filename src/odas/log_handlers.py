"""Log-entry CRUD: the flow behind the routes in `routes_log`.

The routes hold the URLs and the auth; this holds what a save does. Every entry
lands in the audit, so the flow writes that line itself.

An entry may also go out as mail. That is one act: the message leaves first,
and only a message the relay took is filed. The zaak address is the Reply-To,
so the answer comes back into this same log.
"""

from __future__ import annotations

from datetime import date
from email.message import EmailMessage
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from odas import (
    audit,
    clock,
    log_reply,
    log_write,
    mail,
    mail_sent,
    mailin_store,
    schema,
    templating,
    users,
    zaak,
)
from odas.appconfig import mailin_address
from odas.templating import templates
from odas.web_helpers import read_uploads
from odas.zaak_view import zaak_context

TEMPLATE = "log_bewerken.html"


def find_entry(folder: Path, entry_name: str) -> zaak.LogEntry | None:
    """Look an entry up by name. A trailing `.md` is tolerated: identity is the stem."""
    stem = entry_name.removesuffix(".md")
    return next((e for e in zaak.scan_log(folder) if e.name == stem), None)


def audit_entry(folder: Path, by: str, verb: str, direction: str, label: str) -> None:
    """One audit line per log entry made, changed or removed."""
    audit.write(folder, f"log-item {verb} ({direction}): {label}", by=by)


def locked_keys(frontmatter: dict[str, str]) -> list[str]:
    """The recipients of an entry that carries the message itself.

    A `message_id` means `bericht.eml` is filed beside the entry. The message is
    on the wire, so the editor reads those headers out, and a save cannot move them.
    """
    return list(templating.MAIL_KEYS) if frontmatter.get("message_id") else []


def log_edit_context(
    folder: Path, ref: str, entry_name: str, raw: str, error: str | None
) -> dict[str, object]:
    """Context for the log-entry editor form."""
    entry = find_entry(folder, entry_name)
    fm, body, _ = schema.parse_or_raw(raw)
    return {
        "ref": ref,
        "base_url": f"/zaken/{ref}",
        "entry_name": entry_name.removesuffix(".md"),  # canonical identity in every emitted URL
        "fm": fm,
        "body": body,
        "attachments": [p.split("/")[-1] for p in entry.attachments] if entry else [],
        "can_attach": True,  # a flat entry is promoted to a folder on its first attachment
        "direction": entry.direction if entry else "",
        "locked": locked_keys(fm),
        "known": log_reply.known_addresses(zaak.load(folder)),
        "error": error,
    }


def kept_attachments(
    folder: Path, entry: zaak.LogEntry, remove: list[str]
) -> list[tuple[str, bytes]]:
    """The files an entry still holds, as bytes, so a later send can carry them.

    `bericht.eml` is proof of an earlier message, never a document of this one.
    """
    dropped = {Path(name).name for name in remove} | {mailin_store.RAW_NAME}
    files = [(rel, Path(rel).name) for rel in entry.attachments]
    return [(name, (folder / rel).read_bytes()) for rel, name in files if name not in dropped]


async def send_entry(
    ref: str,
    velden: dict[str, str],
    body: str,
    by: str,
    attachments: list[tuple[str, bytes]] | None = None,
) -> EmailMessage:
    """Put a typed entry on the wire. Raises `mail.MailError`, in words a person reads.

    The documents of the entry go with it: what the entry holds is what the
    recipient gets. The relay runs in a worker thread: a relay that does not
    answer must hold this one request and no other.
    """
    to = mail.parse_addresses(velden.get("aan", ""))
    cc = mail.parse_addresses(velden.get("cc", ""))
    if not to and not cc:
        raise mail.MailError("Vul bij Aan of Cc een adres in, of kies Opslaan.")
    try:
        return await run_in_threadpool(
            mail.send,
            to,
            velden.get("onderwerp") or ref,
            body,
            attachments,
            reply_to=mailin_address(ref),
            cc=cc,
            from_name=users.display_name(by),
        )
    except mail.MailError as e:
        raise mail.MailError(f"Versturen is niet gelukt: {e} De tekst staat er nog.") from e


async def handle_log_create(
    request: Request,
    folder: Path,
    ref: str,
    *,
    direction: str,
    entry_date: str,
    velden: dict[str, str],
    body: str,
    documenten: list[UploadFile],
    by: str,
    send: bool = False,
) -> Response:
    """Make one log entry. A refused save comes back on the zaak page it was typed on."""
    content = schema.dump(velden, body, fields=schema.log_fields())
    docs, error = await read_uploads([f for f in documenten if f.filename])

    # The wire first: an entry that claims it went out when it did not is the one
    # state a person cannot recover from.
    msg: EmailMessage | None = None
    mail_error = ""
    if not error and send:
        try:
            msg = await send_entry(ref, velden, body, by, docs)
        except mail.MailError as e:
            error = mail_error = str(e)

    entry_path: Path | None = None
    if not error:
        try:
            # A sent entry is filed from the message itself, so it carries the bytes.
            if msg is not None:
                entry_path = mail_sent.file_sent(
                    folder,
                    msg,
                    body,
                    by=by,
                    direction=direction,
                    entry_date=entry_date,
                    attachments=docs,
                )
            else:
                entry_path = log_write.create_log_entry(
                    folder, direction, entry_date, content, attachments=docs, by=by
                )
        except ValueError as e:
            error = str(e)

    if error or entry_path is None:
        return templates.TemplateResponse(
            request=request,
            name="zaak.html",
            context=zaak_context(
                request,
                folder,
                log_error=error,
                mail_error=mail_error,
                log_fm=velden,
                log_body=body,
                log_direction=direction,
                log_date=entry_date or date.today().isoformat(),
            ),
            status_code=422,
        )

    if msg is None:  # a sent entry writes its own audit line, where the bytes are kept
        audit_entry(folder, by, "aangemaakt", direction, velden.get("onderwerp") or entry_path.name)
    return RedirectResponse(f"/zaken/{ref}", status_code=303)


async def handle_log_edit(
    request: Request,
    folder: Path,
    ref: str,
    entry_name: str,
    *,
    velden: dict[str, str],
    body: str,
    documenten: list[UploadFile],
    verwijder: list[str],
    by: str,
    direction: str = "",
    send: bool = False,
) -> Response:
    """Change one log entry. A refused save comes back in the entry editor.

    A new direction renames the entry: the direction is part of its name.
    An entry that never went out may still go: the wire first, then the file.
    """
    existing = find_entry(folder, entry_name)
    if existing is None:
        raise HTTPException(status_code=404, detail="log-item niet gevonden")

    # Keys read off a received message are not on the form. Start from what is on
    # disk so editing the note text never drops the message's own headers.
    locked = locked_keys(existing.frontmatter)
    fm = {**existing.frontmatter, **{k: v for k, v in velden.items() if k not in locked}}
    # Only a person's edit counts: a line the app adds itself changes no one's words.
    fm["gewijzigd"] = clock.stamp()
    docs, error = await read_uploads([f for f in documenten if f.filename])

    # The wire first, as on a new entry. A page that has gone stale may ask to
    # send what already went: the message is one, so the second ask is refused.
    msg: EmailMessage | None = None
    mail_error = ""
    if not error and send:
        if locked:
            error = "Dit bericht is al verstuurd."
        else:
            try:
                kept = kept_attachments(folder, existing, verwijder)
                msg = await send_entry(ref, fm, body, by, [*kept, *docs])
            except mail.MailError as e:
                error = mail_error = str(e)
    if msg is not None:
        fm = {**fm, **mail_sent.message_fields(msg)}
        docs = [mail_sent.proof(msg), *docs]

    content = schema.dump(fm, body, fields=schema.log_fields())
    if not error:
        try:
            log_write.update_log_entry(
                folder, entry_name, content, attachments=docs, remove=verwijder, direction=direction
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail="log-item niet gevonden") from e
        except ValueError as e:
            error = str(e)

    if error:
        return templates.TemplateResponse(
            request=request,
            name=TEMPLATE,
            context={
                **log_edit_context(folder, ref, entry_name, content, error),
                "mail_error": mail_error,
            },
            status_code=422,
        )

    now = direction or existing.direction
    if msg is not None:
        mail_sent.audit_sent(folder, fm, now, by)
    else:
        audit_entry(folder, by, "bewerkt", now, fm.get("onderwerp") or entry_name)
    return RedirectResponse(f"/zaken/{ref}", status_code=303)
