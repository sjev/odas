"""The indiener's page: one zaak, opened by a capability token, no account.

What the indiener may *see* is tested in test_access.py. This is what they can
*do*: read their zaak, reply to it, and correct the handful of fields the config
marks as theirs. A reply is an ordinary IN log entry -- there is no second
inbox.
"""

from __future__ import annotations

import re
from email.message import EmailMessage
from pathlib import Path

import pytest
from conftest import LEEG, ZAAK, leave_behind, token_of, use_example_data
from fastapi.testclient import TestClient

from odas import log_write, mailin_store, zaak


def test_the_page_shows_the_zaak_and_a_reply_form(client: TestClient) -> None:
    r = client.get(f"/inzien-{token_of(ZAAK)}")
    assert r.status_code == 200
    assert ZAAK in r.text
    assert 'name="onderwerp"' in r.text


def test_the_zaak_page_offers_the_link_the_indiener_opens(client: TestClient) -> None:
    """A jurist mails the link themselves, so the closed page has to show it."""
    r = client.get(f"/zaken/{ZAAK}")

    assert f"/inzien-{token_of(ZAAK)}" in r.text
    assert "Inzienlink" in r.text


def test_the_indiener_never_sees_a_key_outside_the_public_fields(client: TestClient) -> None:
    """Showing the team the whole file did not open the token page with it."""
    leave_behind(LEEG, "oud_kenmerk", "AB-12")
    r = client.get(f"/inzien-{token_of(LEEG)}")
    assert r.status_code == 200
    assert "oud_kenmerk" not in r.text  # undeclared: the team's problem, not theirs
    assert "Toegang" not in r.text  # declared, not public: the grant stays internal


def test_the_reply_form_is_prefilled_with_the_known_contact(client: TestClient) -> None:
    r = client.get(f"/inzien-{token_of(ZAAK)}")
    assert 'name="naam" value="Jan Janssen"' in r.text


def test_a_reply_becomes_an_in_entry_on_the_zaak(client: TestClient) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    r = client.post(
        f"/inzien-{token_of(LEEG)}",
        data={"naam": "Piet", "onderwerp": "Mijn reactie", "bericht": "Hier is mijn aanvulling."},
        files=[("documenten", ("aanvulling.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    )
    assert r.status_code == 200
    assert "ontvangen" in r.text.lower()

    entries = zaak.load(folder).log_entries
    assert len(entries) == 1
    entry = entries[0]
    assert entry.direction == "IN"
    assert entry.frontmatter["onderwerp"] == "Mijn reactie"
    assert entry.body == "Hier is mijn aanvulling."
    assert [p.split("/")[-1] for p in entry.attachments] == ["aanvulling.pdf"]


def test_a_reply_is_attributed_in_the_audit(client: TestClient) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    client.post(
        f"/inzien-{token_of(LEEG)}",
        data={"naam": "Piet Puk", "onderwerp": "Mijn reactie", "bericht": "Aanvulling."},
    )
    assert "[Piet Puk]" in (folder / zaak.AUDIT_FILE).read_text(encoding="utf8")


@pytest.mark.parametrize(
    ("data", "why"),
    [
        ({"naam": "", "onderwerp": "", "bericht": ""}, "nothing filled in"),
        ({"onderwerp": "Reactie", "bericht": "Tekst."}, "no name to attribute it to"),
    ],
)
def test_an_incomplete_reply_is_refused_and_writes_nothing(
    client: TestClient, data: dict[str, str], why: str
) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    r = client.post(f"/inzien-{token_of(LEEG)}", data=data)
    assert r.status_code == 422, why
    assert "verplicht" in r.text
    assert zaak.load(folder).log_entries == []


# ── Correcting the fields the config lends them ───────────────────────────────


def test_the_edit_form_offers_the_public_editable_fields(client: TestClient) -> None:
    r = client.get(f"/inzien-{token_of(ZAAK)}/bewerken")
    assert r.status_code == 200
    assert 'name="fase"' in r.text
    assert 'name="termijn_datum"' in r.text
    assert "51.162741,6.126829" in r.text  # the current locatie, prefilled


def test_an_indiener_edit_persists(client: TestClient) -> None:
    folder = zaak.find(ZAAK)
    assert folder is not None
    r = client.post(
        f"/inzien-{token_of(ZAAK)}/bewerken",
        data={
            "locatie": "Arcen",
            "fase": "zienswijze",
            "termijn_soort": "bezwaar",
            "termijn_datum": "2026-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    fm = zaak.load(folder).frontmatter
    assert fm["locatie"] == "Arcen"
    assert fm["fase"] == "zienswijze"
    assert fm["termijn_soort"] == "bezwaar"
    assert fm["termijn_datum"] == "2026-09-01"


def test_an_invalid_indiener_edit_saves_nothing(client: TestClient) -> None:
    folder = zaak.find(ZAAK)
    assert folder is not None
    before = (folder / "index.md").read_bytes()
    r = client.post(f"/inzien-{token_of(ZAAK)}/bewerken", data={"fase": "ongeldig"})
    assert r.status_code == 422
    assert (folder / "index.md").read_bytes() == before


def test_the_indiener_can_switch_to_the_dark_view(client: TestClient) -> None:
    """The token page carries the same moon button as the team pages, so an
    indiener is not left on the light view alone."""
    r = client.get(f"/inzien-{token_of(ZAAK)}")
    assert 'id="theme-toggle"' in r.text
    assert 'href="/team"' not in r.text  # the switch arrives without the team links


# ── The documents of the visible log items ────────────────────────────────────
#
# The indiener has no account, so every file address on their page must carry
# the token. A team address sends them to the login page instead of the file.


def _anon_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A browser with no cookie at all: the middleware is really in the way."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    from odas.app import create_app

    return TestClient(create_app())


def test_the_indiener_opens_a_document_of_a_visible_log_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A click on an attachment gives the file itself, with no account."""
    with _anon_client(tmp_path, monkeypatch) as c:
        page = c.get(f"/inzien-{token_of(ZAAK)}").text
        href = re.findall(r'href="(/inzien-[^"]*/bijlage/[^"]+)"', page)
        assert href, "the page offers no document of its own"

        r = c.get(href[0], follow_redirects=False)

    assert r.status_code == 200
    folder = zaak.find(ZAAK)
    assert folder is not None
    entry, name = href[0].split("/log/")[1].split("/bijlage/")
    assert r.content == (folder / "log" / entry / name).read_bytes()


def test_the_indiener_page_links_no_team_address(client: TestClient) -> None:
    """One escaped link is enough to drop the indiener on the login page."""
    page = client.get(f"/inzien-{token_of(ZAAK)}").text
    assert 'href="/zaken/' not in page


def test_a_document_of_an_internal_note_is_not_behind_the_token(client: TestClient) -> None:
    """The note is off the page, so guessing its name must not fetch its file."""
    folder = zaak.find(ZAAK)
    assert folder is not None
    entry = log_write.write_log_entry(
        folder,
        "LOG",
        "interne notitie",
        "Niet voor de indiener.",
        attachments=[("geheim.pdf", b"%PDF-1.4 geheim")],
    ).name

    r = client.get(f"/inzien-{token_of(ZAAK)}/log/{entry}/bijlage/geheim.pdf")

    assert r.status_code == 404
    assert b"geheim" not in r.content


def test_the_received_message_itself_is_not_behind_the_token(client: TestClient) -> None:
    """The indiener reads the documents, not the envelope with its kopregels."""
    folder = zaak.find(LEEG)
    assert folder is not None
    entry = mailin_store.file_message(folder, "IN", _a_received_message())
    assert entry is not None

    r = client.get(f"/inzien-{token_of(LEEG)}/log/{entry.name}/bijlage/bericht.eml")

    assert r.status_code == 404


def test_the_indiener_page_offers_no_eml_window(client: TestClient) -> None:
    """The window is a team tool: it shows the headers of the message."""
    folder = zaak.find(LEEG)
    assert folder is not None
    assert mailin_store.file_message(folder, "IN", _a_received_message()) is not None

    assert "data-eml=" in client.get(f"/zaken/{LEEG}").text  # the team keeps it
    assert "data-eml=" not in client.get(f"/inzien-{token_of(LEEG)}").text


def test_a_document_request_that_leaves_the_entry_is_a_404(client: TestClient) -> None:
    """The token opens one entry folder on disk and no other place."""
    r = client.get(f"/inzien-{token_of(ZAAK)}/log/..%2F..%2F..%2Fetc/bijlage/passwd")
    assert r.status_code == 404


def _a_received_message() -> bytes:
    """What a mail client puts on the wire, as `test_log` files one."""
    msg = EmailMessage()
    msg["From"] = "griffie@gemeente.example.nl"
    msg["To"] = "m.dekker@veenwacht.example.nl"
    msg["Subject"] = "Uw bezwaarschrift"
    msg["Date"] = "Wed, 20 May 2026 09:14:00 +0200"
    msg["Message-ID"] = "<bezwaar-002@gemeente.example.nl>"
    msg.set_content("Ontvangen.")
    return msg.as_bytes()
