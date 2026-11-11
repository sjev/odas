"""What this app puts on the wire, and in whose words.

A notice is owed to someone with no account, such as the intake confirmation.
Correspondence is the same act as writing a log entry: the address of the zaak
is the Reply-To, so the answer files itself.

`mail_transport` carries the message; this file builds it. A message either
goes or raises `MailError`, whose text is Dutch because a person reads it.
What a send proves is that the relay took the message, and `mail_sent` keeps
those bytes in the zaak.
"""

from __future__ import annotations

import logging
import mimetypes
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parseaddr

from odas.appconfig import smtp
from odas.mail_transport import MailError, deliver

# `MailError` is raised by the transport and caught by every caller of `send`,
# so it is part of this module's face.
__all__ = [
    "INTAKE_BEVESTIGING",
    "MailError",
    "parse_addresses",
    "sample_values",
    "send",
    "send_template",
]

log = logging.getLogger(__name__)

# The messages the app knows how to send. The words are the data dir's, under
# `smtp.templates`; only these names are code, the way `public_intake` is.
INTAKE_BEVESTIGING = "intake_bevestiging"


def parse_addresses(field: str) -> list[str]:
    """Split 'Naam <a@x>, b@y' into ['a@x', 'b@y']; display names are dropped."""
    return [addr.strip() for _, addr in getaddresses([field or ""]) if addr.strip()]


def _from(name: str) -> str:
    """The organisation's address, with the name of the person who wrote in front.

    The address never moves: it is the one the sending server may sign for.
    """
    configured, address = parseaddr(smtp().sender)
    return formataddr((name or configured, address))


def _build(
    to: list[str],
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]] | None,
    reply_to: str = "",
    cc: list[str] | None = None,
    from_name: str = "",
) -> EmailMessage:
    msg = EmailMessage()
    sender = _from(from_name)
    msg["From"] = sender
    # The relay stamps a message that carries neither, with its own name. A
    # receiver reads that mismatch as a sign of bulk mail.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=parseaddr(sender)[1].rpartition("@")[2] or None)
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.set_content(body)
    for name, content in attachments or []:
        maintype, _, subtype = (
            mimetypes.guess_type(name)[0] or "application/octet-stream"
        ).partition("/")
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=name)
    return msg


def send(
    to: list[str],
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]] | None = None,
    reply_to: str = "",
    cc: list[str] | None = None,
    from_name: str = "",
) -> EmailMessage:
    """Send one message. Returns what went; raises `MailError` when it did not."""
    msg = _build(to, subject, body, attachments, reply_to, cc, from_name)
    deliver(msg, to)
    return msg


def send_template(
    name: str, to: list[str], *, reply_to: str = "", values: dict[str, str] | None = None
) -> EmailMessage | None:
    """Send the named message in the data dir's own words. Raises `MailError` on failure.

    A data dir that declares no template of this name sends nothing and returns
    None. That is the same rule as every other capability: the declaration is
    what makes the feature exist.

    `reply_to` is the address an answer must reach. It is also lent to the words
    as `{zaak_adres}`, so the org can name it where a button alone is not enough.
    """
    template = smtp().templates.get(name)
    if template is None:
        log.info(f"No template declared, nothing sent: name={name!r} to={to!r}")
        return None
    filled = {"zaak_adres": reply_to, **(values or {})}
    try:
        subject = template.onderwerp.format_map(filled)
        body = template.tekst.format_map(filled)
    except (KeyError, IndexError) as e:
        raise MailError(f"Het sjabloon {name} vraagt om {e}, en dat is niet ingevuld.") from e
    return send(to, subject, body, reply_to=reply_to)


class _Sample(dict[str, str]):
    """Any placeholder a template asks for, filled with a visible stand-in."""

    def __missing__(self, key: str) -> str:
        return f"<{key}>"


def sample_values() -> dict[str, str]:
    """Stand-in values, to check the transport and the words without a real zaak."""
    return _Sample(ref="zk-00000", inzien_url="https://voorbeeld.nl/inzien-voorbeeld")
