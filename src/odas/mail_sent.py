"""File a message this app sent, the way a received one is filed.

The proof of sending is the message itself. `mailin_store` keeps the bytes of
what came in; this keeps the bytes of what went out, under the same file name
and the same frontmatter keys, so one template draws both. The zaak log is the
sent folder of the zaak.

What a send proves is that the relay took the message. Whether it reached a
person is answered by a bounce, and a bounce is a message like any other.
"""

from __future__ import annotations

import logging
from email.message import EmailMessage
from pathlib import Path

from odas import audit, log_write, mailin_store, schema

log = logging.getLogger(__name__)


def message_fields(msg: EmailMessage) -> dict[str, str]:
    """The headers a filed message keeps, limited to what this data dir declares."""
    values = {
        "onderwerp": str(msg["Subject"] or ""),
        "aan": str(msg["To"] or ""),
        "cc": str(msg["Cc"] or ""),
        "message_id": str(msg["Message-ID"] or ""),
    }
    declared = schema.log_fields()
    return {k: v for k, v in values.items() if k in declared}


def proof(msg: EmailMessage) -> tuple[str, bytes]:
    """The bytes that went out, under the name a received message is filed with."""
    return (mailin_store.RAW_NAME, msg.as_bytes())


def audit_sent(folder: Path, values: dict[str, str], direction: str, by: str) -> None:
    """One audit line per message that left, beside the line the log entry writes."""
    audit.write(folder, f"e-mail verstuurd ({direction}): {values.get('onderwerp', '')}", by=by)


def file_sent(
    folder: Path,
    msg: EmailMessage,
    body: str,
    *,
    by: str,
    direction: str = "UIT",
    entry_date: str = "",
    attachments: list[tuple[str, bytes]] | None = None,
) -> Path:
    """Write the sent message as one log entry, with `bericht.eml` beside it."""
    values = message_fields(msg)
    content = schema.dump(values, body, schema.log_fields())
    entry = log_write.create_log_entry(
        folder,
        direction,
        entry_date,
        content,
        attachments=[proof(msg), *(attachments or [])],
        by=by,
    )
    audit_sent(folder, values, direction, by)
    log.info(f"Mail filed: ref={folder.name!r} entry={entry.name!r} to={values.get('aan', '')!r}")
    return entry
