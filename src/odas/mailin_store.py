"""Turn a received message into a log entry, keeping the original bytes.

The entry holds `bericht.eml` beside the extracted attachments. That file is the
message itself, so the zaak records what was sent rather than a claim about it.
"""

from __future__ import annotations

import email
import logging
from datetime import datetime
from email.message import EmailMessage
from email.policy import default as email_policy
from email.utils import getaddresses, parseaddr
from pathlib import Path

from odas import audit, clock, htmltext, log_write, mailin_forward, quotes, schema, users, zaak
from odas.appconfig import smtp

log = logging.getLogger(__name__)

RAW_NAME = "bericht.eml"


def parse(raw: bytes) -> EmailMessage:
    msg = email.message_from_bytes(raw, policy=email_policy)
    assert isinstance(msg, EmailMessage)
    return msg


def _addresses(msg: EmailMessage, header: str) -> str:
    """One header as a comma-joined address list; display names are dropped."""
    return ", ".join(a for _, a in getaddresses(msg.get_all(header, [])) if a)


def sender_of(msg: EmailMessage) -> str:
    return _addresses(msg, "From").split(",")[0].strip()


def direction_of(msg: EmailMessage, rcpt: str) -> str:
    """Where the sender put the zaak address: Cc is a note, To came in, Bcc went out.

    A Bcc stands in no header, so an address named nowhere was a Bcc.
    """
    here = rcpt.strip().strip("<>").lower()
    if here in _named(msg, "Cc"):
        return "LOG"
    return "IN" if here in _named(msg, "To") else "UIT"


def _named(msg: EmailMessage, header: str) -> set[str]:
    return {a.lower() for _, a in getaddresses(msg.get_all(header, []))}


def _day(at: datetime | None) -> str:
    """The day of a moment on the clock of the org. No moment gives none: today, then."""
    return clock.local(at).date().isoformat() if at else ""


def body_text(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    return htmltext.part_text(part.get_content(), part.get_content_type())


def _attachments(msg: EmailMessage, raw: bytes) -> list[tuple[str, bytes]]:
    """The original first, so it keeps its name, then every attached part."""
    return [(RAW_NAME, raw), *mailin_forward.files_in(msg)]


def _held_ids(folder: Path) -> set[str]:
    return {e.frontmatter.get("message_id") or "" for e in zaak.scan_log(folder)} - {""}


def already_filed(folder: Path, message_id: str) -> bool:
    """Whether this zaak already holds this message; a Bcc and a forward file once."""
    return bool(message_id) and message_id in _held_ids(folder)


def answers_held(folder: Path, msg: EmailMessage) -> bool:
    """Whether the message answers one the zaak holds, so its quote is a copy."""
    named = " ".join(msg.get_all("In-Reply-To", []) + msg.get_all("References", [])).split()
    return not _held_ids(folder).isdisjoint(named)


def ours(sender: str) -> bool:
    """Whether the organisation or a team member sent this. A directory outage says no."""
    sender = sender.lower()
    if sender == parseaddr(smtp().sender)[1].lower():
        return True
    try:
        return users.is_team(sender)
    except Exception:
        log.warning(f"Directory unreachable, forward kept as sent: from={sender!r}")
        return False


def _heading(fwd: mailin_forward.Forward) -> str:
    """Who wrote the forwarded letter, as a mail client writes it above one."""
    lines = {"Van": fwd.van, "Datum": fwd.datum, "Aan": fwd.aan, "Onderwerp": fwd.onderwerp}
    return "\n".join(["Doorgestuurd bericht:"] + [f"{k}: {v}" for k, v in lines.items() if v])


def file_message(folder: Path, direction: str, raw: bytes) -> Path | None:
    """Write one received message as a log entry. None when it is already there.

    A forward from us is filed as the letter it carries: the wrapper gives the
    entry its correspondents, its day and its subject. A forward from anyone else
    keeps its own headers, so an answer goes back to that person. Either way the
    letter stands whole under the note.
    """
    msg = parse(raw)
    sender = sender_of(msg)
    values = {
        "onderwerp": (msg["Subject"] or "").strip(),
        "van": sender,
        "aan": _addresses(msg, "To"),
        "cc": _addresses(msg, "Cc"),
        "message_id": (msg["Message-ID"] or "").strip(),
    }
    at = mailin_forward.moment(msg["Date"] or "")
    own, letter, datum, files = body_text(msg), "", "", _attachments(msg, raw)

    fwd = mailin_forward.unwrap(msg)
    if fwd is not None:
        own, letter = fwd.note, fwd.body
        files += fwd.attachments
        if ours(sender):
            carried = {"onderwerp": fwd.onderwerp, "van": fwd.van, "aan": fwd.aan, "cc": fwd.cc}
            values |= {k: v for k, v in carried.items() if v}
            values["onderwerp"] = mailin_forward.plain_subject(values["onderwerp"])
            values["message_id"] = fwd.message_id or values["message_id"]
            # A wrapper that gives a day and no time keeps the time of the forward;
            # the page shows no time that falls on another day.
            at = fwd.sent or at
            datum = fwd.datum
        else:
            # The entry keeps the forwarder's headers, so the letter names its own writer.
            letter = f"{_heading(fwd)}\n\n{letter}"

    # Only a quote of a message the zaak holds is a copy; anything else may be
    # the one place that text is kept.
    if answers_held(folder, msg):
        own, _ = quotes.strip_quote(own)
    body = f"{own}\n\n{letter}".strip()

    if already_filed(folder, values["message_id"]):
        log.info(f"Message already filed: ref={folder.name!r} message_id={values['message_id']!r}")
        # The copy did arrive, so the zaak says so even though it gains no entry.
        audit.write(folder, f"e-mail al eerder ontvangen: {values['onderwerp']}", by=sender)
        return None

    # Only what this data dir declares: writing more would put keys on disk that
    # its own schema calls unknown.
    declared = schema.log_fields()
    fm = {k: v for k, v in values.items() if k in declared}
    content = schema.dump(fm, body, declared)
    # The forwarder is the one who delivered it, so the trail names them, not the
    # correspondent the entry now carries.
    by = sender or "e-mail"
    entry = log_write.create_log_entry(
        folder, direction, datum or _day(at), content, attachments=files, by=by, at=at
    )
    audit.write(folder, f"e-mail vastgelegd ({direction}): {values['onderwerp']}", by=by)
    return entry
