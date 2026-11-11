"""The listener that carries `mailin` to the network. It holds no policy.

Encryption lives here, because it is a property of the connection and not of the
message. The daemon offers STARTTLS and never demands it: a sending server that
cannot encrypt still gets its mail filed, since silent loss is the worse failure.
There is nothing to configure. The first run makes the certificate.
"""

from __future__ import annotations

import logging
import ssl
import threading
from pathlib import Path
from typing import Any

from odas import mailin, naming, zaak
from odas.appconfig import mailin as mailin_config
from odas.config import Config
from odas.logging import startup_banner
from odas.settings import MailinSettings

log = logging.getLogger(__name__)


def _make_certificate(cert: Path, key: Path) -> None:
    """Write a self-signed pair that lasts longer than the host will.

    A sending server on port 25 takes the encryption and does not check who
    signed it, so this hides the letter as well as a bought certificate does.
    Put another pair at these paths to use one that is signed.
    """
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    domain = mailin_config().domains[0]
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365 * 10))
        .sign(private, hashes.SHA256())
    )
    cert.parent.mkdir(parents=True, exist_ok=True)
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key.touch(mode=0o600)  # made narrow before it holds anything: the key is a secret
    key.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    log.info(f"Wrote a self-signed certificate for {domain}: {cert}")


def tls_context() -> ssl.SSLContext:
    """The certificate this daemon offers. The first run makes it."""
    cert, key = Config().mail_cert()
    if not cert.exists() or not key.exists():
        _make_certificate(cert, key)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context


def _who(session: Any, envelope: Any) -> str:
    """The connection facts a line carries: who connected, how, and who they claim to be.

    The daemon offers encryption and the sending server decides, so whether a
    letter crossed the network in the clear is a fact about that letter.
    """
    peer = getattr(session, "peer", None)
    tls = getattr(session, "ssl", None)
    cipher = tls.get("cipher") if isinstance(tls, dict) else None
    return (
        f"host={peer[0] if isinstance(peer, tuple) else peer} "
        f"tls={cipher[1] if cipher else 'none'} from={envelope.mail_from!r}"
    )


class Handler:
    """The aiosmtpd shell over `deliver`. It holds no policy of its own."""

    async def handle_RCPT(
        self, server: Any, session: Any, envelope: Any, address: str, rcpt_options: list[str]
    ) -> str:
        """Refuse an address we do not serve now, before the body is transmitted."""
        ref = mailin.parse_recipient(address)
        if ref is not None and zaak.find(ref) is not None:
            envelope.rcpt_tos.append(address)
            return "250 OK"
        reply = f"550 5.1.1 Onbekende zaak: {ref}" if ref else "550 5.1.1 Onbekende ontvanger"
        # A mistyped ref is a person waiting on their mail. Anything else is scan traffic.
        record = log.warning if ref and naming.looks_like_ref(ref) else log.info
        record(f"Address refused: {_who(session, envelope)} rcpt={address!r} reply={reply!r}")
        return reply

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        """One message may name several zaken; the worst reply is the one returned."""
        raw = envelope.original_content or envelope.content
        log.info(
            f"Message received: {_who(session, envelope)} rcpt={envelope.rcpt_tos} size={len(raw)}"
        )
        replies = [mailin.deliver(rcpt, raw) for rcpt in envelope.rcpt_tos]
        return next((r for r in replies if not r.startswith("250")), "250 2.0.0 Vastgelegd")


def listener(config: MailinSettings) -> Any:
    """A started SMTP listener. A data dir that declares no domain gets none."""
    from aiosmtpd.controller import Controller

    if not config.domains:
        raise SystemExit("Geen `mailin.domains` in .app/config.yaml: e-mail wordt niet ontvangen.")

    controller = Controller(
        Handler(),
        hostname="0.0.0.0",
        port=config.port,
        data_size_limit=config.max_bytes,
        tls_context=tls_context(),
        require_starttls=False,  # a sender that cannot encrypt still gets its mail filed
    )
    controller.start()  # the controller runs its own loop in its own thread
    startup_banner(
        "mail capture listening",
        {"port": config.port, "transport": "STARTTLS", "domains": ", ".join(config.domains)},
    )
    return controller


def run() -> None:
    """Listen until interrupted."""
    controller = listener(mailin_config())
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        controller.stop()
