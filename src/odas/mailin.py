"""Decide what happens to a message a zaak address receives.

The listener that carries this to the network is `mailin_server.py`.

A jurist sends from their own client and puts the zaak address in Bcc; an
incoming letter is forwarded to that same address. Either way the copy that
arrives here is the message itself, so there is nothing to keep in step.

Every message to a zaak that exists is filed, from any sender. A lost reply is
worse than a stray one, and a bounce does not reliably reach the sender. The
signature is checked all the same: a sender it does not prove is a warning in
the mail log, so a forged entry can be traced.
"""

from __future__ import annotations

import logging

from odas import mailin_store, zaak
from odas.appconfig import mailin

log = logging.getLogger(__name__)


def parse_recipient(rcpt: str) -> str | None:
    """`<ref>@<domain>` → the ref. None when the domain is not one we answer for.

    Whether the ref names a zaak is the caller's question, not this one's.
    """
    config = mailin()
    local, _, domain = rcpt.strip().strip("<>").rpartition("@")
    if not config.domains or domain.lower() not in {d.lower() for d in config.domains}:
        return None
    return local.lower() or None


def verify_dkim(raw: bytes) -> str | None:
    """The domain whose signature checks out on the raw bytes, or None.

    The domain is the proof that the `From` is real. Without it the entry is
    still filed, and the mail log says so.
    """
    import dkim

    try:
        signature = dkim.DKIM(raw)
        return signature.domain.decode().lower() if signature.verify() else None
    except Exception as exc:
        log.warning(f"DKIM check failed: {exc}")  # the reason, so the warning is explainable
        return None


def covers(signer: str | None, sender: str) -> bool:
    """Whether the signing domain vouches for this sender: their domain or a parent.

    Anyone can sign mail for a domain they own, so a valid signature alone
    proves nothing about the `From` it carries.
    """
    domain = sender.rpartition("@")[2]
    return bool(signer) and (domain == signer or domain.endswith(f".{signer}"))


def deliver(rcpt: str, raw: bytes) -> str:
    """File one received message. Returns the SMTP reply the sender is given.

    A refusal is recorded, so "my mail never arrived" is answered from this side
    rather than by waiting for the sender to forward a bounce.
    """
    reply = _decide(rcpt, raw)
    if not reply.startswith("250"):
        log.warning(f"Mail refused: rcpt={rcpt!r} size={len(raw)} reply={reply!r}")
    return reply


def _decide(rcpt: str, raw: bytes) -> str:
    """The reply this message earns. Every check that can refuse lives here."""
    ref = parse_recipient(rcpt)
    if ref is None:
        return "550 5.1.1 Onbekende ontvanger"
    folder = zaak.find(ref)
    if folder is None:
        return f"550 5.1.1 Onbekende zaak: {ref}"
    if len(raw) > mailin().max_bytes:
        return "552 5.3.4 Bericht te groot"
    signer = verify_dkim(raw)
    msg = mailin_store.parse(raw)
    sender = mailin_store.sender_of(msg).lower()
    if not covers(signer, sender):
        log.warning(f"Unproven sender filed: rcpt={rcpt!r} from={sender!r} signer={signer!r}")

    direction = mailin_store.direction_of(msg, rcpt)
    entry = mailin_store.file_message(folder, direction, raw)
    if entry is None:
        return "250 2.0.0 Al eerder ontvangen"
    log.info(
        f"Mail filed: ref={ref!r} direction={direction!r} entry={entry.name!r} from={sender!r}"
    )
    return f"250 2.0.0 Vastgelegd op {ref}"
