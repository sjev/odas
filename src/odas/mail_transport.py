"""How a message crosses the network, and nothing about what it says.

`smtp.host` in the data dir's config chooses the transport:

- empty       -> there is no transport, so nothing can be sent,
- folder path -> the message is written to that folder as a `.eml` file,
- hostname    -> real SMTP relay.

A message either goes or raises `MailError`. Silence is not a result.
"""

from __future__ import annotations

import logging
import os
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from odas import appsecrets
from odas.appconfig import smtp
from odas.config import Config
from odas.settings import SmtpSettings

log = logging.getLogger(__name__)

TIMEOUT = 10  # seconds; a relay slower than this must not hold the request that waits


class MailError(RuntimeError):
    """A message a person asked for did not go. The text is shown to that person."""


def _to_folder(host: str, msg: EmailMessage, to: list[str]) -> Path:
    """The prototype transport: one file per message, named for when it went.

    A relative path is relative to the data dir, so a config that ships with its
    own outbox needs no absolute path baked into it.
    """
    outbox = Path(host) if Path(host).is_absolute() else Config().data_dir / host
    outbox.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", (to[0] if to else "").lower()).strip("-") or "mail"
    # To the microsecond: two messages in one second must not overwrite each other.
    path = outbox / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{slug}.eml"
    path.write_bytes(msg.as_bytes())
    return path


def _to_relay(config: SmtpSettings, msg: EmailMessage) -> str:
    """Hand the message to the relay. Returns "" when it took it, else the reason."""
    # The stdlib default context verifies neither name nor chain.
    context = ssl.create_default_context()
    try:
        # Port 465 is implicit TLS: the handshake comes before the greeting.
        if config.port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                config.host, config.port, timeout=TIMEOUT, context=context
            )
        else:
            server = smtplib.SMTP(config.host, config.port, timeout=TIMEOUT)
        with server:
            server.ehlo()  # the feature list stays empty until the greeting is answered
            encrypted = isinstance(server, smtplib.SMTP_SSL)
            if not encrypted and server.has_extn("starttls"):
                server.starttls(context=context)
                encrypted = True
            if config.user and not encrypted:
                return f"{config.host} biedt geen STARTTLS, dus het wachtwoord gaat niet mee."
            if config.user:
                server.login(config.user, appsecrets.require("smtp_pass"))
            refused = server.send_message(msg)
    except Exception as e:
        log.exception(f"Relay {config.host} did not take the message")
        return f"{config.host} nam het bericht niet aan: {e}."
    # `smtplib` reports a partly refused message rather than raising on it.
    return f"{config.host} weigerde: {', '.join(refused)}." if refused else ""


def deliver(msg: EmailMessage, to: list[str]) -> None:
    """Put one built message on the wire. Raises `MailError` when it stayed."""
    config = smtp()
    if not config.host:
        raise MailError("Er is geen mailtransport ingesteld (smtp.host is leeg).")

    if os.sep in config.host:  # a folder path, never a host name
        path = _to_folder(config.host, msg, to)
        log.info(f"Email written: to={to!r} transport=disk path={path}")
        return

    if reason := _to_relay(config, msg):
        raise MailError(reason)
    log.info(f"Email sent: to={to!r} subject={str(msg['Subject'])!r} host={config.host}")
