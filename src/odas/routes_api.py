"""JSON API for the AI import agent: create zaken and log entries.

The agent posts structured JSON; the routes
validate and write via `zaak_create`/`log_write`, so the agent never touches raw YAML.
Enabled only in test_mode (local dev); not exposed in production.
"""

from __future__ import annotations

import base64
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odas import log_write, zaak, zaak_create
from odas.config import Config


def require_test_mode() -> None:
    """The JSON /api is local-dev only; refuse outside test mode."""
    if not Config().test_mode:
        raise HTTPException(status_code=403, detail="API unavailable in production")


router = APIRouter(prefix="/api", dependencies=[Depends(require_test_mode)])


class ZaakIn(BaseModel):
    """A zaak of the public-intake type. `velden` carries whatever that type declares."""

    titel: str
    omschrijving: str = ""
    velden: dict[str, str] = {}


class LogEntryIn(BaseModel):
    direction: Literal["IN", "UIT", "LOG"]
    datum: str
    onderwerp: str
    body: str = ""
    aan: str = ""
    attachments: dict[str, str] = {}  # filename -> base64


@router.post("/zaken", status_code=201)
def create_zaak(payload: ZaakIn) -> dict[str, str]:
    """Create a new zaak from intake data."""
    z = zaak_create.create_zaak(
        payload.velden, titel=payload.titel, body=payload.omschrijving, by="api"
    )
    return {"id": z.ref, "folder": z.id}


@router.post("/zaken/{ref}/log", status_code=201)
def create_log_entry(ref: str, payload: LogEntryIn) -> dict[str, str]:
    """Add a log entry (optionally with base64 attachments) to an existing zaak."""
    folder = zaak.find(ref)
    if not folder:
        raise HTTPException(status_code=404, detail=f"Zaak niet gevonden: {ref}")

    attachments: list[tuple[str, bytes]] = []
    for fname, b64 in payload.attachments.items():
        try:
            attachments.append((fname, base64.b64decode(b64)))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Ongeldige bijlage {fname}: {e}") from e

    entry = log_write.write_log_entry(
        folder,
        payload.direction,
        payload.onderwerp,
        payload.body,
        aan=payload.aan,
        attachments=attachments or None,
        by="api",
        datum=payload.datum,
    )
    return {"entry": entry.name}
