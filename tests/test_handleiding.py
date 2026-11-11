"""The manual: one Dutch Markdown page rendered directly for signed-in people."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import SOLO_ZAAK, ZAAK, token_of, use_mailin
from fastapi.testclient import TestClient


def richtingen(html: str) -> list[tuple[str, str]]:
    """The log directions a page names, wherever it draws them.

    The manual writes them as a list and the form as a dropdown, so the tags and
    the dash differ. What must match is the direction and the word beside it.
    """
    text = re.sub(r"<[^>]+>", "", html)
    return re.findall(r"(LOG|UIT|IN) [—-] (interne notitie|uitgaand|ontvangen)", text)


def email_rules(html: str) -> str:
    """The rendered list of e-mail rules, wherever a page draws it."""
    lists = re.findall(r"<ul>.*?</ul>", html, re.S)
    return next((u for u in lists if "<code>UIT</code>: zaakadres in" in u), "")


def nav(html: str) -> str:
    found = re.search(r"<nav.*?</nav>", html, re.S)
    return found.group(0) if found else ""


def test_the_manual_is_one_page_rendered_from_its_markdown_file(client: TestClient) -> None:
    """A person reads the whole short guide without moving between chapters."""
    page = client.get("/handleiding").text

    assert "<strong>zaak</strong>" in page  # `**zaak**` in the Markdown source
    assert "<code>bezwaar</code>" in page  # `` `bezwaar` `` in the Markdown source
    assert "Een zaak aanmaken en terugvinden" in page
    assert "Logboek" in page
    assert "E-mail" in page
    assert "Bcc" in page
    assert "Cc" in page
    assert "bericht doorsturen naar het zaakadres" in page
    assert "Verstuur e-mail" in page  # the button that mails an entry
    assert (
        "al via een andere applicatie hebt verstuurd" in page
    )  # Opslaan records, it does not send


def test_a_wrapped_line_does_not_break_the_sentence_it_belongs_to(client: TestClient) -> None:
    """The files are hard-wrapped prose, so a source newline is not a line break."""
    page = client.get("/handleiding").text

    assert "<br" not in page


def test_the_manual_has_no_chapter_pages(client: TestClient) -> None:
    assert client.get("/handleiding/overzicht").status_code == 404


# ── The menu ──────────────────────────────────────────────────────────────────


def test_every_signed_in_person_is_offered_the_handleiding(client: TestClient) -> None:
    """The manual is for anyone who got in, so the entry is gated on nothing more."""
    assert '<a href="/handleiding">Handleiding</a>' in nav(client.get("/zaken").text)


def test_a_person_who_did_not_sign_in_does_not_read_the_handleiding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary sign-in gate is the only one, and it is not opened here."""
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    from odas.app import app

    with TestClient(app) as c:
        r = c.get("/handleiding", follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"].startswith("/login")


# ── A word copied from another screen ─────────────────────────────────────────


def test_the_manual_names_the_same_log_directions_the_log_form_offers(
    client: TestClient,
) -> None:
    """The file being the page ends drift against the design doc, not against a form."""
    manual = richtingen(client.get("/handleiding").text)
    form = richtingen(client.get(f"/zaken/{ZAAK}").text)

    assert sorted(manual) == sorted(form)
    assert len(manual) == 3


# ── The e-mail help beside the zaak address ───────────────────────────────────


def test_the_manual_keys_the_email_rules_on_the_direction_a_person_wants(
    client: TestClient,
) -> None:
    """A person picks a direction first, then reads which field carries it."""
    page = client.get("/handleiding").text

    assert "<code>UIT</code>: zaakadres in <strong>Bcc</strong>" in page
    assert "<code>IN</code>: bericht doorsturen naar het zaakadres" in page


def test_the_zaak_page_repeats_the_manuals_email_rules_beside_the_address(
    client: TestClient, tmp_path: Path
) -> None:
    """The rule stands where the choice is made, so nobody has to open the manual."""
    use_mailin(tmp_path)
    page = client.get(f"/zaken/{ZAAK}").text

    assert "<code>UIT</code>: zaakadres in <strong>Bcc</strong>" in page
    assert "<code>IN</code>: bericht doorsturen naar het zaakadres" in page
    assert "<code>LOG</code>: zaakadres in <strong>Cc</strong>" in page
    assert 'id="mail-help-dialog"' in page


def test_the_email_help_carries_no_second_copy_of_the_rules(
    client: TestClient, tmp_path: Path
) -> None:
    """The manual is the source, so the dialog quotes it rather than restating it."""
    use_mailin(tmp_path)
    manual = email_rules(client.get("/handleiding").text)
    zaak_page = email_rules(client.get(f"/zaken/{ZAAK}").text)

    assert manual  # the manual states the rules at all
    assert zaak_page == manual  # the same rendered HTML, read from one file


def test_a_zaak_without_a_mail_address_offers_no_email_help(solo_client: TestClient) -> None:
    """This data dir declares no mail capture, so there is nothing to explain."""
    page = solo_client.get(f"/zaken/{SOLO_ZAAK}").text

    assert "Zaak-e-mail" not in page
    assert 'id="mail-help-dialog"' not in page


def test_the_indiener_is_not_shown_the_teams_mail_address(
    client: TestClient, tmp_path: Path
) -> None:
    """The zaak address files mail on the zaak; the indiener has the inzienlink."""
    use_mailin(tmp_path)
    page = client.get(f"/inzien-{token_of(ZAAK)}").text

    assert "Zaak-e-mail" not in page
    assert 'id="mail-help-dialog"' not in page


# ── The search help beside the box ────────────────────────────────────────────


def zoek_examples(html: str) -> list[str]:
    """The `sleutel:waarde` examples the search help gives, in order."""
    section = html.split("<h2>Zoeken</h2>", 1)[-1].split("<h2>", 1)[0]
    return re.findall(r"<code>([a-z_]+:[^<]*)</code>", section)


def test_the_overview_repeats_the_manuals_search_help_beside_the_box(
    client: TestClient,
) -> None:
    """The examples stand where a person types, so nobody has to open the manual."""
    page = client.get("/zaken").text

    assert 'id="zoek-help-dialog"' in page
    assert "<code>status:nieuw</code>" in page
    assert "<code>aangemaakt:2026-07</code>" in page


def test_the_search_help_carries_no_second_copy_of_the_examples(client: TestClient) -> None:
    manual = zoek_examples(client.get("/handleiding").text)
    overview = zoek_examples(client.get("/zaken").text)

    assert manual
    assert overview == manual
