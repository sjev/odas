"""Who forwarded decides what the entry is.

A forward from us brings a letter into the zaak, so the entry is that letter. A
forward from anyone else is that person writing to us, so the entry stays theirs
and an answer goes back to them. Either way the letter stands whole on the page.
"""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest
from conftest import LEEG, fake_users, use_example_data, use_mailin

from odas import log_reply, mailin_store, zaak
from odas.zaak import LogEntry

TEAMLID = "m.dekker@veenwacht.example.nl"
ORG = "noreply@hulpvraag.veenwacht.example.nl"  # smtp.sender of the veenwacht example data
INDIENER = "a.kok@example.nl"
AMBTENAAR = "n.boer@provincie.example.nl"
OUR_MAIL = "<vraag-1@hulpvraag.veenwacht.example.nl>"
LETTER_LINE = "Er is bij ons geen adviesverzoek binnengekomen."


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The empty example zaak, holding one mail we sent, with one team member."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    use_mailin(tmp_path)
    fake_users(monkeypatch, TEAMLID)
    found = zaak.find(LEEG)
    assert found is not None
    sent = EmailMessage()
    sent["From"] = ORG
    sent["To"] = INDIENER
    sent["Subject"] = "Uw hulpvraag"
    sent["Date"] = "Tue, 20 Oct 2026 19:19:00 +0200"
    sent["Message-ID"] = OUR_MAIL
    sent.set_content("Beste Arjen,\n\nDe termijn voor bezwaar is verlopen.\n")
    assert mailin_store.file_message(found, "UIT", sent.as_bytes()) is not None
    return found


def _letter() -> EmailMessage:
    letter = EmailMessage()
    letter["From"] = f"Boer, Niek <{AMBTENAAR}>"
    letter["To"] = INDIENER
    letter["Subject"] = "RE: Vragen over stikstof"
    letter["Date"] = "Thu, 22 Oct 2026 11:42:13 +0200"
    letter["Message-ID"] = "<antwoord-1@provincie.example.nl>"
    letter.set_content(f"Geachte heer Kok,\n\n{LETTER_LINE}\n")
    return letter


def _attached(sender: str) -> bytes:
    """A note that answers our mail, quotes it, and carries the letter attached."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = f"{LEEG}@odas.example.nl"
    msg["Subject"] = "Re: Uw hulpvraag"
    msg["Date"] = "Thu, 22 Oct 2026 13:34:00 +0200"
    msg["Message-ID"] = "<noot-1@example.nl>"
    msg["In-Reply-To"] = OUR_MAIL
    msg.set_content(
        "Beste Emma,\n\nHierbij het antwoord van de provincie.\n\nGrt, Arjen\n\n"
        "> Op 20 okt 2026 heeft Emma het volgende geschreven:\n"
        "> De termijn voor bezwaar is verlopen.\n"
    )
    msg.add_attachment(_letter())
    return msg.as_bytes()


def _inline_html(sender: str) -> bytes:
    """An inline forward the way Apple Mail sends it: HTML alone."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = f"{LEEG}@odas.example.nl"
    msg["Subject"] = "Fwd: Vragen over stikstof"
    msg["Date"] = "Sun, 25 Oct 2026 12:49:00 +0100"
    msg["Message-ID"] = "<fwd-1@example.nl>"
    msg["References"] = OUR_MAIL  # names a held message, yet the letter must stay
    msg.set_content(
        "<p>Vriendelijke groet</p><p>Arjen Kok</p><p>Leeuwarden</p>"
        "<p>Begin doorgestuurd bericht:</p>"
        f"<p>Van: Boer, Niek &lt;{AMBTENAAR}&gt;<br>"
        "Datum: 22 oktober 2026 om 11:42:18 CEST<br>"
        f"Aan: {INDIENER}<br>"
        "Onderwerp: RE: Vragen over stikstof</p>"
        f"<p>Geachte heer Kok,</p><p>{LETTER_LINE}</p>",
        subtype="html",
    )
    return msg.as_bytes()


def _filed(folder: Path, raw: bytes) -> LogEntry:
    assert mailin_store.file_message(folder, "IN", raw) is not None
    return zaak.load(folder).log_entries[-1]


@pytest.mark.parametrize("shape", [_attached, _inline_html])
def test_an_indiener_who_forwards_a_letter_stays_the_sender(folder: Path, shape: object) -> None:
    """The answer goes to the indiener, and the letter they sent stands whole."""
    entry = _filed(folder, shape(INDIENER))  # type: ignore[operator]

    assert entry.frontmatter["van"] == INDIENER
    assert log_reply.reply_form(entry)["aan"] == INDIENER
    assert LETTER_LINE in entry.body
    assert f"Van: {AMBTENAAR}" in entry.body  # who wrote the letter is still on the page


def test_a_note_loses_its_quote_of_our_mail_but_never_the_letter(folder: Path) -> None:
    """Our mail is held already; the letter under the note is not."""
    entry = _filed(folder, _attached(INDIENER))

    assert entry.body.startswith("Beste Emma,")
    assert "De termijn voor bezwaar is verlopen." not in entry.body
    assert entry.body.endswith(LETTER_LINE)


@pytest.mark.parametrize("sender", [TEAMLID, ORG])
@pytest.mark.parametrize("shape", [_attached, _inline_html])
def test_a_forward_from_us_is_filed_as_the_letter_it_carries(
    folder: Path, sender: str, shape: object
) -> None:
    """A colleague or the org mailbox brings the letter in, so the entry is the letter."""
    entry = _filed(folder, shape(sender))  # type: ignore[operator]

    assert entry.frontmatter["van"] == AMBTENAAR
    assert entry.frontmatter["onderwerp"] == "RE: Vragen over stikstof"
    assert entry.name.startswith("2026-10-22-")
    assert LETTER_LINE in entry.body


def test_a_forward_from_a_colleague_keeps_its_own_headers_while_the_directory_is_down(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No answer is no proof of a colleague, so nothing is rewritten."""

    def unreachable() -> list[object]:
        raise ConnectionError("pocket-id unreachable")

    monkeypatch.setattr("odas.users.load_users", unreachable)

    entry = _filed(folder, _attached(TEAMLID))

    assert entry.frontmatter["van"] == TEAMLID
    assert LETTER_LINE in entry.body


def test_a_quote_of_a_message_the_zaak_does_not_hold_stays(folder: Path) -> None:
    """Text the zaak does not hold may be the only copy, so it is kept."""
    msg = EmailMessage()
    msg["From"] = INDIENER
    msg["To"] = f"{LEEG}@odas.example.nl"
    msg["Subject"] = "Re: Iets anders"
    msg["Message-ID"] = "<los-1@example.nl>"
    msg["In-Reply-To"] = "<elders-1@example.nl>"
    msg.set_content("Beste Emma,\n\nZie hieronder.\n\nGrt, Arjen\n\n> Een tekst van elders.\n")

    entry = _filed(folder, msg.as_bytes())

    assert entry.body.endswith("> Een tekst van elders.")
    assert "weggelaten" not in entry.body
