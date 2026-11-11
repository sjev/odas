"""Request-level helpers shared by the route modules: who is asking, and may they.

The access rule itself lives in `access`, which needs no `Request`. Template
context lives in `zaak_view`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
from starlette.datastructures import UploadFile  # the base class: accepts both flavours

from odas import access, zaak
from odas.appconfig import demo, log_fields

_MAX_FILES = 150
_MAX_FILE_BYTES = 150 * 1024 * 1024


def require_team(request: Request) -> None:
    refusal = access.create_refusal(access.of(request))
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)


def require_admin(request: Request) -> None:
    """The team, outside a demonstration. There every visitor is the team, and the
    logs hold the addresses of the others who mailed it."""
    if demo() is not None:
        raise HTTPException(status_code=404, detail="pagina niet gevonden")
    require_team(request)


def zaak_folder(request: Request, zaak_id: str) -> Path:
    """Resolve zaak_id to its folder, enforcing access.

    A zaak the viewer holds no grant on answers 404, the same as one that does not
    exist: the number of zaken we hold is itself not theirs to learn.
    """
    folder = zaak.find(zaak_id)
    if folder is None or not access.may_access(access.of(request), zaak.load_safe(folder)):
        raise HTTPException(status_code=404, detail="zaak niet gevonden")
    return folder


def token_folder(token: str) -> Path:
    """Resolve a reply token to its zaak folder. Raises 404."""
    folder = zaak.find_by_token(token)
    if folder is None:
        raise HTTPException(status_code=404, detail="pagina niet gevonden")
    return folder


def get_by(request: Request) -> str:
    return access.actor(access.of(request))


async def log_values(request: Request) -> dict[str, str]:
    """The submitted log-entry fields, taken from what `fields.log` declares.

    Iterate the declared keys, never the submitted ones: an injected key is never
    read. A key the data dir marks `editable: []` is read off a received message,
    so it is not the form's to set and does not appear here at all.
    """
    form = await request.form()
    declared = log_fields().items()
    return {k: str(form.get(k, "")).strip() for k, f in declared if "team" in f.editable}


async def read_uploads(files: list[UploadFile]) -> tuple[list[tuple[str, bytes]], str | None]:
    """Read uploaded files into (name, bytes) pairs; second item is a Dutch error or None."""
    if len(files) > _MAX_FILES:
        return [], f"Maximaal {_MAX_FILES} bestanden."
    docs: list[tuple[str, bytes]] = []
    error: str | None = None
    for f in files:
        content = await f.read()
        if len(content) > _MAX_FILE_BYTES:
            error = f"'{f.filename}' is te groot (max 150 MB)."
        docs.append((f.filename or "", content))
    return docs, error
