"""The reply button on a mail entry: a new entry, addressed as a mail client would."""

from __future__ import annotations

import html
import re
from email.message import EmailMessage
from pathlib import Path

from conftest import GRANTEE, LEEG, TEAMLID, ZAAK, post_log
from fastapi.testclient import TestClient

from odas import mailin_store, zaak

BASE = f"/zaken/{LEEG}"


def _folder() -> Path:
    folder = zaak.find(LEEG)
    assert folder is not None
    return folder


def _received(subject: str = "Uw bezwaarschrift") -> None:
    msg = EmailMessage()
    msg["From"] = "Griffie Venlo <griffie@gemeente.example.nl>"
    msg["To"] = "m.dekker@veenwacht.example.nl"
    msg["Cc"] = "advocaat@example.org"
    msg["Subject"] = subject
    msg["Message-ID"] = "<bezwaar-001@gemeente.example.nl>"
    msg.set_content("Vóór 1 juni een reactie, alstublieft.")
    assert mailin_store.file_message(_folder(), "IN", msg.as_bytes()) is not None


def _reply_href(page: str) -> str:
    found = re.search(r'<a href="([^"]*)"[^>]*class="[^"]*reply-link', page)
    assert found is not None
    return html.unescape(found.group(1))


def _value(form: str, name: str) -> str:
    found = re.search(rf'<input[^>]*name="{name}"[^>]*value="([^"]*)"', form)
    assert found is not None
    return html.unescape(found.group(1))


def test_reply_opens_a_new_entry_to_the_sender_with_re_before_the_subject(
    client: TestClient,
) -> None:
    """A click on the reply arrow opens the new-entry form, addressed and titled."""
    _received()

    page = client.get(_reply_href(client.get(BASE).text)).text

    form = re.search(r'<form[^>]*id="log-form"[^>]*>', page)
    assert form is not None and " hidden" not in form.group(0)  # the form stands open
    assert "griffie@gemeente.example.nl" in _value(page, "aan")
    assert _value(page, "cc") == "advocaat@example.org"
    assert _value(page, "onderwerp") == "RE: Uw bezwaarschrift"
    assert '<option value="UIT" selected' in page  # an answer goes out


def test_a_typed_note_has_no_reply_button(client: TestClient) -> None:
    """A note names its writer, not an address, so there is no one to answer."""
    post_log(client, BASE, onderwerp="Dossier doorgenomen", body="Notitie.")

    assert "reply-link" not in client.get(BASE).text


def test_a_reply_to_a_reply_gets_no_second_re(client: TestClient) -> None:
    _received("Re: Uw bezwaarschrift")

    page = client.get(_reply_href(client.get(BASE).text)).text

    assert _value(page, "onderwerp") == "Re: Uw bezwaarschrift"


def test_a_reply_to_our_own_mail_goes_to_its_recipients_again(client: TestClient) -> None:
    """The sender of an UIT entry is us, so the answer goes where the first one went."""
    post_log(
        client,
        BASE,
        direction="UIT",
        onderwerp="Uw hulpvraag",
        body="Tekst.",
        aan="b@example.org",
        cc="c@example.org",
    )

    page = client.get(_reply_href(client.get(BASE).text)).text

    assert _value(page, "aan") == "b@example.org"
    assert _value(page, "cc") == "c@example.org"


def test_an_unknown_entry_to_reply_to_leaves_the_form_closed(client: TestClient) -> None:
    page = client.get(f"{BASE}?reply=bestaat-niet").text

    form = re.search(r'<form[^>]*id="log-form"[^>]*>', page)
    assert form is not None and " hidden" in form.group(0)


def test_the_send_check_knows_the_indiener_and_the_team(client: TestClient) -> None:
    """Only these addresses go out unmarked; any other one shows in red."""
    page = client.get(f"/zaken/{ZAAK}").text

    form = re.search(r'<form[^>]*id="log-form"[^>]*data-known="([^"]*)"', page)
    assert form is not None
    assert form.group(1).split(",") == ["jan.janssen@example.com", TEAMLID]
    assert GRANTEE not in form.group(1)  # an account outside the team is no colleague
