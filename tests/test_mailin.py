"""Mail capture: the zaak holds the message that was actually sent.

A jurist composes and sends in their own mail client and puts the zaak's address
in Bcc. ODAS receives that copy and files it. The stored `bericht.eml` is the
message itself, byte for byte, so there is no second version to keep in step.

A zaak has one address, and where the sender puts it says what the entry becomes:
a Bcc stands in no header and went out, an address in To or a forward came in, and
a Cc is a copy the reader sees too, so it is filed as a note.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import smtplib
import socket
import ssl
import time
from collections.abc import Iterator
from contextlib import contextmanager
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from conftest import LEEG, fake_users, use_example_data, use_mailin
from fastapi.testclient import TestClient

from odas import zaak

JURIST = "m.dekker@veenwacht.example.nl"


def _sent_message() -> bytes:
    """The bytes a mail client puts on the wire, Bcc stripped as every client does."""
    msg = EmailMessage()
    msg["From"] = f"Marijke Dekker <{JURIST}>"
    msg["To"] = "griffie@rechtbank.example.nl"
    msg["Cc"] = "collega@veenwacht.example.nl"
    msg["Subject"] = "Bezwaarschrift kapvergunning"
    msg["Date"] = "Wed, 20 May 2026 09:14:00 +0200"
    msg["Message-ID"] = "<bezwaar-001@veenwacht.example.nl>"
    msg.set_content("Hierbij het bezwaarschrift.")
    msg.add_attachment(
        b"%PDF-1.4 bezwaar", maintype="application", subtype="pdf", filename="bezwaar.pdf"
    )
    return msg.as_bytes()


def test_a_bcc_copy_is_filed_as_the_message_that_was_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bcc the zaak address and the zaak gains that exact message as a UIT entry."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    use_mailin(tmp_path, domain="odas.example.nl")

    from odas import mailin

    monkeypatch.setattr(
        mailin, "verify_dkim", lambda raw: "veenwacht.example.nl"
    )  # signed by the sender's relay
    raw = _sent_message()

    reply = mailin.deliver(f"{LEEG}@odas.example.nl", raw)

    assert reply.startswith("250")
    folder = zaak.find(LEEG)
    assert folder is not None
    entry = zaak.load(folder).log_entries[0]

    assert entry.name == "2026-05-20-A-UIT-bezwaarschrift-kapvergunning"  # date from the header
    assert entry.direction == "UIT"
    assert entry.body == "Hierbij het bezwaarschrift."
    assert entry.frontmatter["van"] == JURIST
    assert entry.frontmatter["aan"] == "griffie@rechtbank.example.nl"
    assert entry.frontmatter["cc"] == "collega@veenwacht.example.nl"
    assert entry.frontmatter["message_id"] == "<bezwaar-001@veenwacht.example.nl>"

    names = sorted(p.split("/")[-1] for p in entry.attachments)
    assert names == ["bericht.eml", "bezwaar.pdf"]
    assert (folder / "log" / entry.name / "bezwaar.pdf").read_bytes() == b"%PDF-1.4 bezwaar"
    # The whole point: what is filed is the message, not a rendering of it.
    assert (folder / "log" / entry.name / "bericht.eml").read_bytes() == raw


def _html_only_message() -> bytes:
    """A client that sends no plain part at all, as a newsletter or a webmail does."""
    msg = EmailMessage()
    msg["From"] = f"Marijke Dekker <{JURIST}>"
    msg["To"] = "griffie@rechtbank.example.nl"
    msg["Subject"] = "Stand van zaken"
    msg["Date"] = "Wed, 20 May 2026 09:14:00 +0200"
    msg["Message-ID"] = "<html-001@veenwacht.example.nl>"
    msg.set_content(
        "<html><body><p>Beste griffie,</p><p>3. derde punt</p></body></html>",
        subtype="html",
    )
    return msg.as_bytes()


def test_a_message_without_a_plain_part_is_filed_as_readable_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The log holds text a person reads, so an HTML-only mail loses its tags on the way in."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    use_mailin(tmp_path, domain="odas.example.nl")

    from odas import mailin

    monkeypatch.setattr(mailin, "verify_dkim", lambda raw: "veenwacht.example.nl")

    assert mailin.deliver(f"{LEEG}@odas.example.nl", _html_only_message()).startswith("250")

    folder = zaak.find(LEEG)
    assert folder is not None
    entry = zaak.load(folder).log_entries[0]
    assert entry.body == "Beste griffie,\n\n3. derde punt"
    assert "<" not in entry.body


# ── Who may write: any sender, to a zaak that exists ──────────────────────────


def _signed_by_the_sender(raw: bytes) -> str:
    """Stand in for a signature that covers the sender's own domain."""
    return str(message_from_bytes(raw)["From"]).rpartition("@")[2].strip("> ")


@pytest.fixture
def capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The veenwacht example data with capture on and a valid signature.

    The forwarders below are ours: colleagues, and the org mailbox that sent the
    real Dutch export. A forward from anyone else is `test_mailin_forward.py`.
    """
    use_example_data("veenwacht", tmp_path, monkeypatch)
    use_mailin(tmp_path, domain="odas.example.nl")
    fake_users(monkeypatch, JURIST, FORWARDER, DUTCH_FORWARDER)

    from odas import mailin

    monkeypatch.setattr(mailin, "verify_dkim", _signed_by_the_sender)
    return mailin


@pytest.mark.parametrize(
    ("rcpt", "why"),
    [
        ("zk-99999@odas.example.nl", "no such zaak"),
        ("uit.zk-48595@odas.example.nl", "the old direction prefix is not a ref"),
        ("zk-48595@ergensanders.nl", "a domain we do not serve"),
        ("info@odas.example.nl", "a local part that is no ref at all"),
    ],
)
def test_an_address_we_do_not_serve_is_refused(capture: ModuleType, rcpt: str, why: str) -> None:
    """Nothing is filed and the sender's own server makes the bounce."""
    assert capture.deliver(rcpt, _sent_message()).startswith("550"), why
    assert zaak.load(zaak.find(LEEG)).log_entries == []  # type: ignore[arg-type]


def test_an_unsigned_letter_from_a_stranger_is_filed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A member of the public replies from their ISP, unsigned, and the letter lands in the zaak."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    use_mailin(tmp_path, domain="odas.example.nl")
    from odas import mailin

    msg = EmailMessage()
    msg["From"] = "vlier3@delta.example.nl"
    msg["To"] = f"{LEEG}@odas.example.nl"
    msg["Subject"] = "Re: uw zaak"
    msg["Date"] = "Sat, 26 Sep 2026 10:33:00 +0200"
    msg.set_content("Hierbij de gevraagde stukken.")

    assert mailin.deliver(f"{LEEG}@odas.example.nl", msg.as_bytes()).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[0]  # type: ignore[arg-type]
    assert entry.direction == "IN"
    assert entry.frontmatter["van"] == "vlier3@delta.example.nl"
    assert "Hierbij de gevraagde stukken." in entry.body


@pytest.mark.parametrize(
    ("signer", "why"),
    [(None, "no signature"), ("aanvaller.example.com", "a signature from another domain")],
)
def test_an_unproven_sender_is_filed_with_a_warning_in_the_mail_log(
    capture: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    mail_log: pytest.LogCaptureFixture,
    signer: str | None,
    why: str,
) -> None:
    """The entry lands, and the operator can still see that its From: is not proven."""
    monkeypatch.setattr(capture, "verify_dkim", lambda raw: signer)

    assert capture.deliver(f"{LEEG}@odas.example.nl", _sent_message()).startswith("250"), why

    assert zaak.load(zaak.find(LEEG)).log_entries != []  # type: ignore[arg-type]
    record = next(r for r in mail_log.records if "Unproven sender" in r.message)
    assert record.levelname == "WARNING"
    assert JURIST in record.message  # the address that claims to have sent it


def test_a_message_over_the_size_limit_is_refused(
    capture: ModuleType,
    tmp_path: Path,
) -> None:
    import yaml
    from conftest import write_config

    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["mailin"]["max_bytes"] = 100
    write_config(tmp_path, config)

    assert capture.deliver(f"{LEEG}@odas.example.nl", _sent_message()).startswith("552")


def test_mail_is_filed_while_the_account_list_is_down(
    capture: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headers alone give the direction, so pocket-id being down delays nothing."""

    def unreachable() -> list[object]:
        raise ConnectionError("pocket-id unreachable")

    monkeypatch.setattr("odas.users.load_users", unreachable)

    assert capture.deliver(f"{LEEG}@odas.example.nl", _sent_message()).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[0]  # type: ignore[arg-type]
    assert entry.direction == "UIT"  # the Bcc copy of a sent message


# ── Filing ────────────────────────────────────────────────────────────────────


# ── The day is the day here, not the day the sender wrote ─────────────────────

# 20 Aug 2026 22:28 UTC is 21 Aug 00:28 in Amsterdam. A client that writes its
# Date in UTC must not cost the entry a day.
LATE_NIGHT = "Thu, 20 Aug 2026 22:28:07 +0000"


@pytest.fixture
def amsterdam() -> Iterator[None]:
    """The house clock, so the test does not read the developer's own zone."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Amsterdam"
    time.tzset()
    yield
    if before is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = before
    time.tzset()


def test_a_message_sent_late_at_night_is_filed_on_the_day_here(
    capture: ModuleType, amsterdam: None
) -> None:
    """A Date header in UTC states an instant. The entry says which local day that was."""
    msg = message_from_bytes(_sent_message(), policy=policy.default)
    del msg["Date"]
    msg["Date"] = LATE_NIGHT

    assert capture.deliver(f"{LEEG}@odas.example.nl", msg.as_bytes()).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[0]  # type: ignore[arg-type]
    assert entry.name.startswith("2026-08-21-")


def test_a_forwarded_letter_sent_late_at_night_keeps_the_day_here(amsterdam: None) -> None:
    """The letter inside a wrapper is read by the same clock as the wrapper itself."""
    from odas import mailin_forward

    assert mailin_forward._day(LATE_NIGHT) == "2026-08-21"


def test_the_same_message_arriving_twice_is_filed_once(capture: ModuleType) -> None:
    """A Bcc and a colleague's forward of one message are one thing that happened."""
    raw = _sent_message()
    assert capture.deliver(f"{LEEG}@odas.example.nl", raw).startswith("250")
    assert capture.deliver(f"{LEEG}@odas.example.nl", raw).startswith("250")

    assert len(zaak.load(zaak.find(LEEG)).log_entries) == 1  # type: ignore[arg-type]


def _forward(headers: dict[str, str], subject: str = "Doorgestuurd") -> bytes:
    """A message a jurist addresses to the zaak openly, rather than in Bcc."""
    msg = EmailMessage()
    msg["From"] = JURIST
    msg["Subject"] = subject
    msg["Date"] = "Wed, 20 May 2026 09:14:00 +0200"
    msg["Message-ID"] = f"<{subject}@veenwacht.example.nl>"
    for header, value in headers.items():
        msg[header] = value
    msg.set_content("Zie onder.")
    return msg.as_bytes()


def test_the_message_says_which_way_it_went(capture: ModuleType) -> None:
    """A Bcc'd copy went out. The same jurist forwarding to the zaak came in."""
    address = f"{LEEG}@odas.example.nl"

    assert capture.deliver(address, _sent_message()).startswith("250")  # Bcc: in no header
    assert capture.deliver(address, _forward({"To": address})).startswith("250")

    entries = zaak.load(zaak.find(LEEG)).log_entries  # type: ignore[arg-type]
    filed = {e.frontmatter["onderwerp"]: e.direction for e in entries}
    assert filed == {"Bezwaarschrift kapvergunning": "UIT", "Doorgestuurd": "IN"}


@pytest.mark.parametrize(
    ("headers", "why"),
    [
        ({"To": "{A}"}, "an address is not case sensitive"),
        ({"To": "griffie@rechtbank.example.nl, {a}"}, "one recipient among several"),
    ],
)
def test_a_zaak_addressed_in_the_to_came_in(
    capture: ModuleType, headers: dict[str, str], why: str
) -> None:
    """Only an invisible recipient means the sender was copying their own message."""
    address = f"{LEEG}@odas.example.nl"
    filled = {k: v.format(a=address, A=address.upper()) for k, v in headers.items()}

    assert capture.deliver(address, _forward(filled, subject=why)).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[0]  # type: ignore[arg-type]
    assert entry.direction == "IN", why


def test_the_zaak_address_in_the_cc_files_a_note(capture: ModuleType) -> None:
    """A copy the reader sees as well is one for the file, and claims no direction."""
    address = f"{LEEG}@odas.example.nl"
    msg = EmailMessage()
    msg["From"] = JURIST
    msg["To"] = "griffie@rechtbank.example.nl"
    msg["Cc"] = address
    msg["Subject"] = "Kopie voor het dossier"
    msg["Date"] = "Wed, 20 May 2026 09:14:00 +0200"
    msg.set_content("Ter kennisname.")

    assert capture.deliver(address, msg.as_bytes()).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[0]  # type: ignore[arg-type]
    assert entry.direction == "LOG"
    assert entry.frontmatter["van"] == JURIST  # the correspondents stay on the note
    assert entry.frontmatter["aan"] == "griffie@rechtbank.example.nl"


def test_a_dossier_captures_mail_like_any_zaak(capture: ModuleType) -> None:
    """A dossier is a zaak, so its ds- ref addresses one too."""
    from conftest import DOSSIER

    reply = capture.deliver(f"{DOSSIER}@odas.example.nl", _sent_message())

    assert reply.startswith("250")
    assert zaak.load(zaak.find(DOSSIER)).log_entries[-1].direction == "UIT"  # type: ignore[arg-type]


# ── The zaak's own history says a message arrived ─────────────────────────────


def test_a_filed_message_is_a_line_in_the_history_of_the_zaak(capture: ModuleType) -> None:
    """A team reads on the zaak that mail arrived, beside their own edits."""
    assert capture.deliver(f"{LEEG}@odas.example.nl", _sent_message()).startswith("250")

    history = zaak.load(zaak.find(LEEG)).history  # type: ignore[arg-type]
    assert f"[{JURIST}] e-mail vastgelegd (UIT): Bezwaarschrift kapvergunning" in history


def test_a_second_copy_of_one_message_says_so_on_the_same_trail(capture: ModuleType) -> None:
    """The forward did arrive, so the trail says it arrived and was already there."""
    address = f"{LEEG}@odas.example.nl"
    assert capture.deliver(address, _sent_message()).startswith("250")
    assert capture.deliver(address, _sent_message()).startswith("250")

    lines = zaak.load(zaak.find(LEEG)).history.splitlines()  # type: ignore[arg-type]
    assert lines[-1].endswith("e-mail al eerder ontvangen: Bezwaarschrift kapvergunning")
    assert len([line for line in lines if "e-mail" in line]) == 2  # both arrivals, one entry


# ── A forward files the letter it carries ─────────────────────────────────────

FORWARDED = Path(__file__).parent / "data" / "emails" / "forwarded_mail.eml"
FORWARD_NL = Path(__file__).parent / "data" / "emails" / "forward_nl.eml"


def _sent_to_leeg(eml: Path) -> bytes:
    """A real forward, readdressed to the empty zaak: the direction reads that header."""
    to = f"To: {LEEG}@odas.example.nl".encode()
    return re.sub(rb"^To: [^\r\n]*", to, eml.read_bytes(), count=1, flags=re.M)


FORWARDER = "jan@visser.example.nl"
DUTCH_FORWARDER = "hulpvraag@veenwacht.example.nl"
CORRESPONDENT = "woo@gemeente.example.nl"


def _wrapped(note: str = "", sent: str = "August 7, 2026 at 10:49 AM") -> bytes:
    """A letter a mail client forwards inline, wrapper prose and all."""
    msg = EmailMessage()
    msg["From"] = FORWARDER
    msg["To"] = f"{LEEG}@odas.example.nl"
    msg["Subject"] = "Fwd: Antwoord op het verzoek"
    msg["Date"] = "Mon, 10 Aug 2026 11:10:00 +0200"
    msg["Message-ID"] = "<doorgestuurd-1@visser.example.nl>"
    msg.set_content(
        f"{note}-------- Forwarded message -------\n"
        "\n"
        f'From: "woo" <{CORRESPONDENT} mailto:{CORRESPONDENT}?to=%22woo%22 >\n'
        f'To: "Jan Visser" <{FORWARDER}>\n'
        f"Cc: {CORRESPONDENT}\n"
        f"Sent: {sent}\n"
        "Subject: Antwoord op het verzoek\n"
        "\n"
        "Geachte heer Visser,\n"
        "\n"
        "Uw verzoek is ontvangen.\n"
    )
    return msg.as_bytes()


def _dutch_wrapper(tail: str) -> bytes:
    """A forward the way a Dutch client writes it, ending in the caller's lines."""
    msg = EmailMessage()
    msg["From"] = FORWARDER
    msg["To"] = f"{LEEG}@odas.example.nl"
    msg["Subject"] = "Fwd: Antwoord op het verzoek"
    msg["Date"] = "Mon, 10 Aug 2026 11:10:00 +0200"
    msg["Message-ID"] = "<doorgestuurd-2@visser.example.nl>"
    msg.set_content(
        "-------- Oorspronkelijke bericht --------\n"
        "Onderwerp: Antwoord op het verzoek\n"
        "Datum: 2026-08-07 10:49\n"
        f"Afzender: woo <{CORRESPONDENT}>\n" + tail
    )
    return msg.as_bytes()


def _letter(message_id: str = "<brief-1@gemeente.example.nl>") -> EmailMessage:
    """The letter itself, as a client attaches it to a forward."""
    inner = EmailMessage()
    inner["From"] = f"Woo-functionaris <{CORRESPONDENT}>"
    inner["To"] = FORWARDER
    inner["Subject"] = "Besluit op uw verzoek"
    inner["Date"] = "Fri, 07 Aug 2026 10:49:00 +0200"
    inner["Message-ID"] = message_id
    inner.set_content("Hierbij het besluit.")
    inner.add_attachment(
        b"%PDF-1.4 besluit", maintype="application", subtype="pdf", filename="besluit.pdf"
    )
    return inner


def _attached_forward(sender: str = FORWARDER, letter: EmailMessage | None = None) -> bytes:
    """A forward that carries the letter whole, the way Outlook attaches it."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = f"{LEEG}@odas.example.nl"
    msg["Subject"] = "FW: Besluit op uw verzoek"
    msg["Date"] = "Mon, 10 Aug 2026 11:10:00 +0200"
    msg["Message-ID"] = f"<door-{sender}@example.nl>"
    msg.set_content("Ter behandeling.")
    msg.add_attachment(letter or _letter())
    return msg.as_bytes()


def test_a_forwarded_letter_is_filed_as_the_letter_it_carries(capture: ModuleType) -> None:
    """Forward a letter and the entry is that letter: its sender, day and subject."""
    raw = _sent_to_leeg(FORWARDED)

    assert capture.deliver(f"{LEEG}@odas.example.nl", raw).startswith("250")

    folder = zaak.find(LEEG)
    assert folder is not None
    entry = zaak.load(folder).log_entries[0]

    assert entry.name.startswith("2026-08-07-A-IN-")  # the day the letter was sent
    assert entry.direction == "IN"
    assert entry.frontmatter["van"] == CORRESPONDENT
    assert entry.frontmatter["aan"] == FORWARDER
    assert entry.frontmatter["cc"] == CORRESPONDENT
    assert entry.frontmatter["onderwerp"].startswith("RE: Zaak 100200")  # the Fwd: came off
    assert entry.body.startswith("Geachte heer Visser")
    assert "Forwarded message" not in entry.body
    # The wrapper is dropped from the entry, never from the record.
    assert (folder / "log" / entry.name / "bericht.eml").read_bytes() == raw


def test_a_covering_note_stays_above_the_forwarded_letter(capture: ModuleType) -> None:
    """What the forwarder typed is theirs, so it stays on top of the message."""
    assert capture.deliver(f"{LEEG}@odas.example.nl", _wrapped("Ter behandeling.\n\n")).startswith(
        "250"
    )

    entry = zaak.load(zaak.find(LEEG)).log_entries[0]  # type: ignore[arg-type]
    assert entry.body.startswith("Ter behandeling.")
    assert entry.body.endswith("Uw verzoek is ontvangen.")
    assert entry.frontmatter["van"] == CORRESPONDENT


def test_an_unreadable_sent_line_falls_back_on_the_day_of_the_forward(
    capture: ModuleType,
) -> None:
    """A guess that fails costs the day of the letter, never the entry."""
    assert capture.deliver(f"{LEEG}@odas.example.nl", _wrapped(sent="gisteren")).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[0]  # type: ignore[arg-type]
    assert entry.name.startswith("2026-08-10-A-IN-")
    assert entry.frontmatter["van"] == CORRESPONDENT  # the rest of the wrapper still counts


def test_a_letter_attached_whole_is_read_from_its_own_headers(capture: ModuleType) -> None:
    """A message attached as a message needs no guessing at prose."""
    assert capture.deliver(f"{LEEG}@odas.example.nl", _attached_forward()).startswith("250")

    folder = zaak.find(LEEG)
    assert folder is not None
    entry = zaak.load(folder).log_entries[0]

    assert entry.name.startswith("2026-08-07-A-IN-besluit-op-uw-verzoek")
    assert entry.frontmatter["van"] == CORRESPONDENT
    assert entry.frontmatter["aan"] == FORWARDER
    assert entry.frontmatter["message_id"] == "<brief-1@gemeente.example.nl>"
    assert entry.body.startswith("Ter behandeling.")  # the covering note
    assert "Hierbij het besluit." in entry.body
    assert (folder / "log" / entry.name / "besluit.pdf").read_bytes() == b"%PDF-1.4 besluit"


def test_two_colleagues_forwarding_one_letter_file_it_once(capture: ModuleType) -> None:
    """The zaak records what happened, and the letter arrived once."""
    address = f"{LEEG}@odas.example.nl"

    assert capture.deliver(address, _attached_forward(FORWARDER)).startswith("250")
    assert capture.deliver(address, _attached_forward(JURIST)).startswith("250")

    entries = zaak.load(zaak.find(LEEG)).log_entries  # type: ignore[arg-type]
    assert [e.frontmatter["message_id"] for e in entries] == ["<brief-1@gemeente.example.nl>"]


def test_a_forward_that_ccs_the_zaak_is_a_note(capture: ModuleType) -> None:
    """The Cc is the sender's own choice, so it holds even over a forwarded letter."""
    address = f"{LEEG}@odas.example.nl"
    msg = EmailMessage()
    msg["From"] = FORWARDER
    msg["To"] = "griffie@rechtbank.example.nl"
    msg["Cc"] = address
    msg["Subject"] = "FW: Besluit op uw verzoek"
    msg["Date"] = "Mon, 10 Aug 2026 11:10:00 +0200"
    msg["Message-ID"] = "<door-cc@example.nl>"
    msg.set_content("Ter kennisname.")
    msg.add_attachment(_letter())

    assert capture.deliver(address, msg.as_bytes()).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[0]  # type: ignore[arg-type]
    assert entry.direction == "LOG"
    assert entry.frontmatter["van"] == CORRESPONDENT  # still filed as the letter it carries


def test_a_dutch_wrapper_is_read_like_any_other(capture: ModuleType) -> None:
    """A Dutch mail client names its wrapper in Dutch, and the letter still opens."""

    assert capture.deliver(f"{LEEG}@odas.example.nl", _sent_to_leeg(FORWARD_NL)).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[0]  # type: ignore[arg-type]
    assert entry.name.startswith("2026-08-13-A-IN-")  # the day the letter was sent
    assert entry.frontmatter["van"] == "h.bos@example.org"
    assert entry.frontmatter["aan"] == f"{DUTCH_FORWARDER}, jan@visser.example.nl"
    assert entry.frontmatter["onderwerp"] == "Re: Testbericht voor nieuwe methode"
    assert entry.body.startswith("Gelukt.")
    assert "Oorspronkelijke bericht" not in entry.body


def test_a_recipient_line_the_client_wrapped_keeps_both_addresses(
    capture: ModuleType,
) -> None:
    """A client breaks a long recipient line; the second address is still a recipient."""
    msg = _dutch_wrapper(
        f"Ontvanger: {CORRESPONDENT}, Jan Visser \n<{FORWARDER}>\n\nUw verzoek is ontvangen.\n"
    )

    assert capture.deliver(f"{LEEG}@odas.example.nl", msg).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[0]  # type: ignore[arg-type]
    assert entry.frontmatter["aan"] == f"{CORRESPONDENT}, {FORWARDER}"
    assert entry.body == "Uw verzoek is ontvangen."


def test_a_wrapper_without_a_blank_line_keeps_its_first_body_line(
    capture: ModuleType,
) -> None:
    """Prose under the last header is the letter, never part of that header."""
    msg = _dutch_wrapper(f"Ontvanger: {FORWARDER}\nGeachte heer Visser,\n")

    assert capture.deliver(f"{LEEG}@odas.example.nl", msg).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[0]  # type: ignore[arg-type]
    assert entry.frontmatter["aan"] == FORWARDER
    assert entry.body == "Geachte heer Visser,"


def test_a_reply_that_quotes_an_earlier_message_is_not_a_forward(capture: ModuleType) -> None:
    """A quote further down is the writer's own answer, so the entry is theirs."""
    msg = EmailMessage()
    msg["From"] = FORWARDER
    msg["To"] = f"{LEEG}@odas.example.nl"
    msg["Subject"] = "Re: Antwoord op het verzoek"
    msg["Date"] = "Mon, 10 Aug 2026 11:10:00 +0200"
    msg.set_content(
        "Geachte mevrouw,\n\nDank voor uw bericht. Ik reageer hieronder.\n\n"
        "-----Oorspronkelijk bericht-----\n"
        f"Van: woo <{CORRESPONDENT}>\n"
        "Verzonden: vrijdag 7 augustus 2026 10:49\n"
        "Onderwerp: Antwoord op het verzoek\n\n"
        "Geachte heer Visser,\n"
    )

    assert capture.deliver(f"{LEEG}@odas.example.nl", msg.as_bytes()).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[0]  # type: ignore[arg-type]
    assert entry.frontmatter["van"] == FORWARDER
    assert entry.frontmatter["onderwerp"] == "Re: Antwoord op het verzoek"
    assert entry.body.startswith("Geachte mevrouw,")
    assert "Oorspronkelijk bericht" in entry.body  # the quote is body text, not a wrapper


# ── The address the page shows is the address the daemon parses ──────────────


def test_the_zaak_page_shows_the_one_address_the_daemon_accepts(client: TestClient) -> None:
    """One helper builds it and the daemon parses it, so they cannot drift."""
    from odas import mailin
    from odas.appconfig import mailin_address

    page = client.get(f"/zaken/{LEEG}").text
    address = mailin_address(LEEG)

    assert address in page
    assert mailin.parse_recipient(address) == LEEG


# ── The trail: a message that is not in the log never arrived ─────────────────


@pytest.fixture
def mail_log(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """The daemon's own lines. `setup_logging` stops propagation to the root logger."""
    loggers = [logging.getLogger(f"odas.{name}") for name in ("mailin", "mailin_server")]
    for logger in loggers:
        logger.addHandler(caplog.handler)
        caplog.set_level(logging.INFO, logger=logger.name)
    yield caplog
    for logger in loggers:
        logger.removeHandler(caplog.handler)


PEER = SimpleNamespace(peer=("198.51.100.7", 51234))


def _shell(capture: ModuleType) -> ModuleType:
    """The listener over the policy `capture` holds."""
    from odas import mailin_server

    return mailin_server


def _offer(capture: ModuleType, address: str) -> tuple[str, SimpleNamespace]:
    """Offer one recipient, as a sending server does before it transmits a body."""
    envelope = SimpleNamespace(mail_from=JURIST, rcpt_tos=[])
    reply = asyncio.run(_shell(capture).Handler().handle_RCPT(None, PEER, envelope, address, []))
    return reply, envelope


def test_a_mistyped_reference_is_recorded_before_any_body_arrives(
    capture: ModuleType, mail_log: pytest.LogCaptureFixture
) -> None:
    """A member mistypes the ref. The trace is on this side, not only in their bounce."""
    reply, envelope = _offer(capture, "zk-12354@odas.example.nl")

    assert reply.startswith("550")
    assert envelope.rcpt_tos == []  # nothing was accepted, so no body follows
    record = next(r for r in mail_log.records if "zk-12354" in r.message)
    assert record.levelname == "WARNING"  # a person's mistake, not background noise
    assert "550" in record.message  # what the sender was told
    assert "198.51.100.7" in record.message  # which server tried
    assert JURIST in record.message  # and who sent it


def test_a_port_scan_is_recorded_without_raising_a_warning(
    capture: ModuleType, mail_log: pytest.LogCaptureFixture
) -> None:
    """Port 25 is scanned all day. Those lines must not bury a member's mistake."""
    reply, _ = _offer(capture, "admin@odas.example.nl")

    assert reply.startswith("550")
    record = next(r for r in mail_log.records if "admin@odas.example.nl" in r.message)
    assert record.levelname == "INFO"


def test_a_refused_message_is_recorded_for_the_operator(
    capture: ModuleType, mail_log: pytest.LogCaptureFixture
) -> None:
    """ "Mijn mail kwam niet aan" is answerable from the log, not only from the bounce."""
    reply = capture.deliver("zk-99999@odas.example.nl", _sent_message())

    assert reply.startswith("550")
    assert "zk-99999@odas.example.nl" in mail_log.text  # which address was tried
    assert "550" in mail_log.text  # and what the sender was told


def test_a_filed_message_leaves_a_line_naming_the_sender_and_the_size(
    capture: ModuleType, mail_log: pytest.LogCaptureFixture
) -> None:
    """The trail carries enough to match a line against what the sender says they sent."""
    raw = _sent_message()
    envelope = SimpleNamespace(
        mail_from=JURIST,
        rcpt_tos=[f"{LEEG}@odas.example.nl"],
        content=raw,
        original_content=raw,
    )

    reply = asyncio.run(_shell(capture).Handler().handle_DATA(None, PEER, envelope))

    assert reply.startswith("250")
    assert str(len(raw)) in mail_log.text  # the size, so a truncated send is visible
    assert JURIST in mail_log.text
    assert LEEG in mail_log.text


def test_the_daemon_says_why_a_signature_could_not_be_checked(
    mail_log: pytest.LogCaptureFixture,
) -> None:
    """A refusal that names no cause is silence to whoever reads the log."""
    from odas import mailin

    assert mailin.verify_dkim(b"dit is geen bericht") is None
    assert "Unexpected characters" in mail_log.text  # the reason, not just that it failed


# ── Encryption: correspondence must not cross the network in the clear ────────


def _free_port() -> int:
    """A port nothing else holds. aiosmtpd cannot bind port 0: it probes what it asked for."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def _daemon(capture: ModuleType) -> Iterator[int]:
    """Start the real listener. Yields the port a sending server connects to."""
    from odas.appconfig import mailin
    from odas.settings import MailinSettings

    config = MailinSettings(domains=mailin().domains, port=_free_port())
    controller = _shell(capture).listener(config)
    try:
        yield config.port
    finally:
        controller.stop()


def _send(port: int, encrypt: bool) -> None:
    """Send the jurist's message to the empty zaak, as a sending server does."""
    client = smtplib.SMTP("127.0.0.1", port, timeout=10)
    client.ehlo()
    if encrypt:
        context = ssl.create_default_context()
        context.check_hostname = False  # the pair is self-signed, which is the whole design
        context.verify_mode = ssl.CERT_NONE
        client.starttls(context=context)
    client.sendmail(JURIST, [f"{LEEG}@odas.example.nl"], _sent_message())
    client.quit()


def _filed_sender() -> str:
    return str(zaak.load(zaak.find(LEEG)).log_entries[0].frontmatter["van"])  # type: ignore[arg-type]


def test_a_sending_server_is_offered_encryption(capture: ModuleType) -> None:
    """Capture is encrypted with no certificate to obtain and nothing to declare."""
    with _daemon(capture) as port:
        client = smtplib.SMTP("127.0.0.1", port, timeout=10)
        client.ehlo()
        assert "starttls" in client.esmtp_features  # what a sending server looks for
        client.quit()

        _send(port, encrypt=True)

    assert _filed_sender() == JURIST  # it arrived, over the encrypted connection


@pytest.mark.parametrize(
    ("encrypt", "expected"),
    [(True, "tls=TLSv1"), (False, "tls=none")],  # 1.2 or 1.3, whatever the two agree
)
def test_the_trail_says_whether_a_letter_arrived_encrypted(
    capture: ModuleType, mail_log: pytest.LogCaptureFixture, encrypt: bool, expected: str
) -> None:
    """The daemon offers encryption and the sender decides, so each letter answers for itself."""
    with _daemon(capture) as port:
        _send(port, encrypt=encrypt)

    line = next(r.message for r in mail_log.records if "Message received" in r.message)
    assert expected in line
    assert _filed_sender() == JURIST  # the same line covers a letter that was filed


def test_a_sender_that_cannot_encrypt_is_still_served(capture: ModuleType) -> None:
    """Losing a letter is worse than carrying it in the clear, so plain delivery stands."""
    with _daemon(capture) as port:
        _send(port, encrypt=False)

    assert _filed_sender() == JURIST


def test_the_mail_log_marks_where_the_daemon_starts(capture: ModuleType, tmp_path: Path) -> None:
    """An operator reads mail.log and sees the release, the port and the domains served."""
    from odas import __version__
    from odas.logging import setup_logging

    setup_logging("mail")
    with _daemon(capture) as port:
        pass
    text = (tmp_path / ".app" / "logs" / "mail.log").read_text(encoding="utf8")

    assert f"ODAS {__version__}: mail capture listening" in text
    assert f"port:         {port}" in text
    assert "domains:      odas.example.nl" in text


def test_the_daemon_makes_its_certificate_once_and_keeps_it(
    capture: ModuleType, tmp_path: Path
) -> None:
    """A restart must not mint a new identity: the pair is written, then reused."""
    cert = tmp_path / ".app" / "mail.crt"

    with _daemon(capture):
        pass
    made = cert.read_bytes()
    with _daemon(capture):
        pass

    assert cert.read_bytes() == made
    assert (tmp_path / ".app" / "mail.key").stat().st_mode & 0o777 == 0o600  # it is a secret


def test_a_certificate_put_in_place_by_hand_is_the_one_offered(
    capture: ModuleType, tmp_path: Path
) -> None:
    """A signed certificate replaces the made one by being at the same path."""
    with _daemon(capture):
        pass
    own = (tmp_path / ".app" / "mail.crt").read_bytes()

    with _daemon(capture) as port:
        client = smtplib.SMTP("127.0.0.1", port, timeout=10)
        client.ehlo()
        unverified = ssl.create_default_context()
        unverified.check_hostname = False
        unverified.verify_mode = ssl.CERT_NONE
        client.starttls(context=unverified)
        offered = client.sock.getpeercert(binary_form=True)  # type: ignore[union-attr]
        client.quit()

    assert ssl.DER_cert_to_PEM_cert(offered).encode() == own


def test_a_team_member_reads_the_mail_log_in_the_app(client: TestClient, tmp_path: Path) -> None:
    """The daemon has no screen, so the team reads its file from the web server."""
    logs = tmp_path / ".app" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "mail.log").write_text("2026-08-10 [WARNING] geweigerd: zk-99999\n", encoding="utf8")

    assert "geweigerd: zk-99999" in client.get("/log/mail").text
    assert "geweigerd: zk-99999" not in client.get("/log").text  # the web log is its own page


# ── A reply does not repeat the message it answers ────────────────────────────

QUOTE_LINE = "Mag ik vandaag van u vernemen?"
MARKER = "*[eerder bericht weggelaten]*"
ASKED = "<vraag-1@provincie.example.nl>"


@pytest.fixture
def asked(capture: ModuleType) -> ModuleType:
    """The zaak holds the message the reply answers, so its quote is a copy."""
    msg = EmailMessage()
    msg["From"] = "Verhoeven <a.verhoeven@provincie.example.nl>"
    msg["To"] = f"{LEEG}@odas.example.nl"
    msg["Subject"] = "Antwoord op het verzoek"
    msg["Date"] = "Tue, 25 Aug 2026 09:12:00 +0200"
    msg["Message-ID"] = ASKED
    msg.set_content(QUOTE_LINE)
    assert capture.deliver(f"{LEEG}@odas.example.nl", msg.as_bytes()).startswith("250")
    return capture


def _reply(quote: str, subject: str = "RE: Antwoord op het verzoek") -> bytes:
    """A reply the way a client writes one: new words, then the old message."""
    msg = EmailMessage()
    msg["From"] = f"Marijke Dekker <{JURIST}>"
    msg["To"] = CORRESPONDENT
    msg["Subject"] = subject
    msg["Date"] = "Wed, 26 Aug 2026 09:14:00 +0200"
    msg["Message-ID"] = f"<antwoord-{abs(hash(quote))}@veenwacht.example.nl>"
    msg["In-Reply-To"] = ASKED
    msg.set_content(
        "Geachte mevrouw,\n"
        "\n"
        "Dank voor uw bericht van 26 augustus 2026.\n"
        "De perceelnummers volgen hieronder.\n"
        "\n"
        "Met vriendelijke groet,\n"
        "M. Dekker\n"
        "06-24517684\n"
        "\n" + quote
    )
    return msg.as_bytes()


ANGLE_QUOTE = (
    "On wo, aug 26 2026 at 07:12:27 +00:00, Verhoeven <a.verhoeven@provincie.example.nl> wrote:\n"
    f"> Beste heer Visser,\n"
    f"> \n"
    f"> {QUOTE_LINE}\n"
    "> \n"
    "> Met vriendelijke groet,\n"
)
DUTCH_MARKER_QUOTE = (
    "-----Oorspronkelijk bericht-----\n"
    f"Van: Verhoeven <a.verhoeven@provincie.example.nl>\n"
    "Verzonden: woensdag 26 augustus 2026 09:12\n"
    f"Aan: Marijke Dekker <{JURIST}>\n"
    "Onderwerp: Antwoord op het verzoek\n"
    "\n"
    "Beste heer Visser,\n"
    "\n"
    f"{QUOTE_LINE}\n"
)


@pytest.mark.parametrize("quote", [ANGLE_QUOTE, DUTCH_MARKER_QUOTE])
def test_a_reply_does_not_repeat_the_message_it_quotes(asked: ModuleType, quote: str) -> None:
    """The old message is already a log entry, so the reply keeps only its own words."""
    assert asked.deliver(f"{LEEG}@odas.example.nl", _reply(quote)).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[-1]  # type: ignore[arg-type]
    assert "De perceelnummers volgen hieronder." in entry.body
    assert "M. Dekker" in entry.body  # the sign-off is the sender's own, so it stays
    assert QUOTE_LINE not in entry.body


def test_a_shortened_entry_says_that_text_was_removed(asked: ModuleType) -> None:
    """A reader sees where the quoted message was, so nothing goes missing silently."""
    assert asked.deliver(f"{LEEG}@odas.example.nl", _reply(ANGLE_QUOTE)).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[-1]  # type: ignore[arg-type]
    assert entry.body.endswith(MARKER)


def test_the_original_message_is_kept_beside_a_shortened_entry(asked: ModuleType) -> None:
    """Shortening touches the entry only. The message itself stays on disk, whole."""
    raw = _reply(ANGLE_QUOTE)
    assert asked.deliver(f"{LEEG}@odas.example.nl", raw).startswith("250")

    folder = zaak.find(LEEG)
    assert folder is not None
    entry = zaak.load(folder).log_entries[-1]
    assert (folder / "log" / entry.name / "bericht.eml").read_bytes() == raw
    assert QUOTE_LINE in (folder / "log" / entry.name / "bericht.eml").read_text()


def test_a_message_without_a_quote_is_written_whole(asked: ModuleType) -> None:
    """Nothing to cut means nothing is cut, and no marker appears."""
    assert asked.deliver(f"{LEEG}@odas.example.nl", _reply("")).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[-1]  # type: ignore[arg-type]
    assert entry.body.endswith("06-24517684")
    assert MARKER not in entry.body


def test_a_forwarded_letter_keeps_the_whole_body_it_carries(capture: ModuleType) -> None:
    """A forward is the letter, not a quote of it, so its words survive in full."""
    assert capture.deliver(
        f"{LEEG}@odas.example.nl", _dutch_wrapper("\nUw verzoek is ontvangen.\n")
    ).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[-1]  # type: ignore[arg-type]
    assert entry.body == "Uw verzoek is ontvangen."
    assert MARKER not in entry.body


WRAPPED_ATTRIBUTION = (
    'On wo, aug 26 2026 at 07:12:27 +00:00:00, "Verhoeven, Annet" \n'
    "<a.verhoeven@provincie.example.nl> wrote:\n"
    f"> {QUOTE_LINE}\n"
)


def test_the_line_that_names_the_quoted_sender_goes_with_the_quote(asked: ModuleType) -> None:
    """A client wraps that line over two, so neither may stay behind as a loose end."""
    assert asked.deliver(f"{LEEG}@odas.example.nl", _reply(WRAPPED_ATTRIBUTION)).startswith("250")

    entry = zaak.load(zaak.find(LEEG)).log_entries[-1]  # type: ignore[arg-type]
    assert "Verhoeven" not in entry.body
    assert entry.body.endswith(f"06-24517684\n\n{MARKER}")
