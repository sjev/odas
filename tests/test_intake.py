"""How a zaak comes into being: the public intake form and the team's own button.

Both end in the same place -- one folder under `zaken/`, with an `index.md`
whose fields come from the type registry and an `audit.log` opened with a single
"zaak aangemaakt" line.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import VEENWACHT_ZAKEN, eml_files, read_msg, use_outbox, write_config
from fastapi.testclient import TestClient
from httpx2 import Response

from odas import naming, zaak, zaak_create
from odas.intake_answers import TITEL_MAX


@pytest.fixture
def client(client: TestClient, tmp_path: Path) -> TestClient:
    """The veenwacht data without its own form, so /indienen is the builtin one."""
    (tmp_path / ".app" / "intake.html").unlink(missing_ok=True)
    return client


def _capture_mail(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[str]]]:
    """Record what would be sent, without a transport. Returns the (name, to) log."""
    sent: list[tuple[str, list[str]]] = []

    def fake_send(name: str, to: list[str], **kwargs: Any) -> None:
        sent.append((name, to))
        return None

    monkeypatch.setattr("odas.mail.send_template", fake_send)
    return sent


def test_intake_creates_a_zaak_from_the_public_form(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _capture_mail(monkeypatch)

    r = client.post(
        "/indienen",
        data={
            "titel": "Kapvergunning boom",
            "omschrijving": "Zorgen over een vergunning.",
            "contact_naam": "A. de Vries",
            "contact_email": "a@example.org",
            "mail_toestemming": "nee",
        },
    )
    assert r.status_code == 200
    ref = re.search(r"zk-\d{5}", r.text).group()  # type: ignore[union-attr]
    assert ref in r.text  # the confirmation shows the reference

    folder = zaak.find(ref)
    assert folder is not None and folder.name.endswith("-kapvergunning-boom")
    z = zaak.load(folder)
    assert z.status == "nieuw"
    assert z.titel == "Kapvergunning boom"
    assert z.frontmatter["contact_naam"] == "A. de Vries"
    assert z.frontmatter["contact_email"] == "a@example.org"
    assert z.body.strip() == "Zorgen over een vergunning."  # the description is the body
    assert sent == [("intake_bevestiging", ["a@example.org"])]  # confirmation fired


def test_the_public_form_asks_exactly_what_the_type_declares(client: TestClient) -> None:
    """Declaring a public field is what puts it on the form; no release changes the questions."""
    form = client.get("/indienen").text

    assert 'name="titel"' in form  # every zaak needs a name, whatever the type
    assert 'name="omschrijving"' in form  # and a description, which becomes the body
    assert 'name="contact_naam"' in form  # declared public and public-editable by this type
    assert 'name="contact_email"' in form
    assert 'name="behandelaar"' not in form  # declared, but the team assigns it, not the public
    assert 'name="telefoon"' not in form  # not declared at all, so never asked


def test_the_public_form_lets_an_indiener_pick_the_place_on_a_map(client: TestClient) -> None:
    """The location field on the form gets the same map button the zaak editor has."""
    form = client.get("/indienen").text

    assert 'name="locatie"' in form
    assert 'class="edit-btn map-pick" data-target="locatie-input"' in form
    assert 'id="map-dialog"' in form
    assert "/static/map_picker.js" in form


def test_a_data_dir_that_declares_no_public_intake_has_no_form(solo_client: TestClient) -> None:
    """One jurist starts their own procedures, so a stranger has nothing to submit."""
    assert solo_client.get("/indienen").status_code == 404


def test_intake_documents_land_as_one_log_entry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uploads are log entries like any other -- no separate documenten/ folder."""
    _capture_mail(monkeypatch)
    r = client.post(
        "/indienen",
        data={
            "titel": "Nieuwe zaak",
            "omschrijving": "Zorgen.",
            "contact_naam": "A. de Vries",
            "contact_email": "a@example.org",
            "mail_toestemming": "nee",
        },
        files=[
            ("documenten", ("besluit.pdf", b"%PDF-1.4 fake", "application/pdf")),
            ("documenten", ("foto.png", b"\x89PNG\r\n\x1a\n", "image/png")),
        ],
    )
    assert r.status_code == 200
    ref = re.search(r"zk-\d{5}", r.text).group()  # type: ignore[union-attr]
    folder = zaak.find(ref)
    assert folder is not None
    assert not (folder / "documenten").exists()

    z = zaak.load(folder)
    entry = z.log_entries[0]
    assert entry.direction == "IN"
    assert entry.frontmatter["onderwerp"] == "indiening"
    assert sorted(p.split("/")[-1] for p in entry.attachments) == ["besluit.pdf", "foto.png"]
    assert (folder / "log" / entry.name / "besluit.pdf").read_bytes() == b"%PDF-1.4 fake"
    assert "zaak aangemaakt" in z.history.splitlines()[0]  # attachments add no audit line


def test_intake_refuses_an_incomplete_form(client: TestClient) -> None:
    r = client.post("/indienen", data={"titel": "", "omschrijving": "", "contact_email": ""})
    assert r.status_code == 422
    assert "verplicht" in r.text
    assert len(zaak.list_ids()) == VEENWACHT_ZAKEN  # nothing created


def _field_block(html: str, key: str) -> str:
    """The <label> block that holds the input for `key`."""
    return next((b for b in html.split("<label>") if f'name="{key}"' in b), "")


def test_the_intake_form_names_each_field_a_person_left_empty(client: TestClient) -> None:
    """A person who leaves out the contact name and address sees an error at each field."""
    r = client.post("/indienen", data={"titel": "Kap", "omschrijving": "Zorgen."})
    assert r.status_code == 422
    assert "Dit veld is verplicht." in _field_block(r.text, "contact_naam")
    assert "Dit veld is verplicht." in _field_block(r.text, "contact_email")
    assert len(zaak.list_ids()) == VEENWACHT_ZAKEN  # nothing created


def test_the_intake_form_asks_the_browser_to_block_an_empty_required_field(
    client: TestClient,
) -> None:
    """The browser stops the submit itself, so a person is not sent back to the top."""
    r = client.get("/indienen")
    assert "required" in _field_block(r.text, "contact_naam")
    assert "required" in _field_block(r.text, "contact_email")
    assert "required" in _field_block(r.text, "titel")
    assert f'maxlength="{TITEL_MAX}"' in _field_block(r.text, "titel")
    assert "required" not in _field_block(r.text, "bekendmaking_url")  # not asked for


def test_the_intake_form_keeps_what_a_person_already_typed_after_an_error(
    client: TestClient,
) -> None:
    r = client.post(
        "/indienen",
        data={"titel": "Kap", "omschrijving": "Zorgen.", "contact_naam": "Jan Jansen"},
    )
    assert 'value="Jan Jansen"' in _field_block(r.text, "contact_naam")
    assert "Dit veld is verplicht." not in _field_block(r.text, "contact_naam")


def test_the_team_still_creates_a_zaak_without_the_contact_fields(client: TestClient) -> None:
    """`public_required` binds the public form alone, so the team button is untouched."""
    r = client.post("/zaken", data={"titel": "Ontgronding"}, follow_redirects=False)
    assert r.status_code == 303
    ref = r.headers["location"].rsplit("/", 1)[-1]
    folder = zaak.find(ref)
    assert folder is not None
    assert zaak.load(folder).frontmatter["contact_naam"] == ""


def test_intake_refuses_an_address_the_email_field_rejects(client: TestClient) -> None:
    """The field kind owns the check, so the form cannot disagree with what disk accepts."""
    r = client.post(
        "/indienen",
        data={
            "titel": "Kap",
            "omschrijving": "Zorgen.",
            "contact_naam": "A. de Vries",
            "contact_email": "geen-adres",
        },
    )
    assert r.status_code == 422
    assert len(zaak.list_ids()) == VEENWACHT_ZAKEN  # nothing created


def test_the_team_creates_a_zaak_from_a_titel_alone(client: TestClient) -> None:
    r = client.post("/zaken", data={"titel": "Ontgronding bij de Maas"}, follow_redirects=False)
    assert r.status_code == 303
    ref = r.headers["location"].rsplit("/", 1)[-1]

    folder = zaak.find(ref)
    assert folder is not None and folder.name.endswith("-ontgronding-bij-de-maas")
    z = zaak.load(folder)
    assert z.status == "nieuw"
    assert z.titel == "Ontgronding bij de Maas"  # the titel is a field, not body text
    assert z.body == ""  # the report lines are fields now, never body text
    assert z.token  # ReplyTokenField.initial() ran at creation, not on first view


@pytest.mark.parametrize(
    ("soort", "prefix"), [("hulpvraag", "zk"), ("dossier", "ds"), ("overleg", "ov")]
)
def test_a_new_zaak_carries_the_prefix_its_type_declares(
    client: TestClient, soort: str, prefix: str
) -> None:
    """The kenmerk says what kind of zaak it is, on screen and in the folder name."""
    z = zaak_create.create_minimal(f"Proef {soort}", soort)

    folder = zaak.find(z.ref)
    assert folder is not None and folder.name.startswith(f"{prefix}-")
    assert zaak.load(folder).frontmatter["id"] == z.ref
    assert re.fullmatch(rf"{prefix}-\d{{5}}", z.ref)


def test_an_empty_titel_creates_nothing(client: TestClient) -> None:
    r = client.post("/zaken", data={"titel": "  "}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/zaken"
    assert len(zaak.list_ids()) == VEENWACHT_ZAKEN


def test_a_new_ref_never_collides_with_an_existing_zaak(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    draws = iter([42817, 11111])  # the first draw collides with the example zaak zk-42817
    monkeypatch.setattr("odas.naming.random.randint", lambda a, b: next(draws))
    assert naming.mint_ref("zk") == "zk-11111"


def test_a_type_without_a_reply_token_never_gets_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`discussion: {}` is a complete, usable type -- and so it has no reply page."""
    from conftest import LOG_FIELDS, write_config

    monkeypatch.setenv("ODAS_TEST_MODE", "1")
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    write_config(tmp_path, {"types": {"discussion": {}}, "fields": LOG_FIELDS})

    from odas.app import create_app
    from odas.appconfig import get_config

    get_config.cache_clear()
    with TestClient(create_app()) as c:
        r = c.post(
            "/zaken", data={"titel": "Overleg", "soort": "discussion"}, follow_redirects=False
        )
        ref = r.headers["location"].rsplit("/", 1)[-1]
        folder = zaak.find(ref)
        assert folder is not None
        assert zaak.load(folder).token == ""  # nothing minted for a type that declares none

        before = (folder / "index.md").stat().st_mtime_ns
        assert c.get(f"/zaken/{ref}").status_code == 200
        assert (folder / "index.md").stat().st_mtime_ns == before  # a view writes nothing


def _capture_values(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Record the substitutions of the last template sent, without a transport."""
    values: dict[str, str] = {}

    def fake_send(name: str, to: list[str], **kwargs: Any) -> None:
        values.update(kwargs.get("values") or {})
        return None

    monkeypatch.setattr("odas.mail.send_template", fake_send)
    return values


def _submit(client: TestClient, headers: dict[str, str]) -> Response:
    return client.post(
        "/indienen",
        data={
            "titel": "Kapvergunning boom",
            "omschrijving": "Zorgen over een vergunning.",
            "contact_naam": "A. de Vries",
            "contact_email": "a@example.org",
            "mail_toestemming": "nee",
        },
        headers=headers,
    )


def test_the_confirmation_is_answerable_at_the_zaak_address(
    client: TestClient, tmp_path: Path
) -> None:
    """The indiener presses Reply, and the answer goes to the address of their zaak."""
    outbox = use_outbox(tmp_path)

    r = client.post(
        "/indienen",
        data={
            "titel": "Kapvergunning boom",
            "omschrijving": "Zorgen over een vergunning.",
            "contact_naam": "A. de Vries",
            "contact_email": "a@example.org",
            "mail_toestemming": "nee",
        },
    )
    ref = re.search(r"zk-\d{5}", r.text).group()  # type: ignore[union-attr]

    msg = read_msg(eml_files(outbox)[0])
    adres = f"{ref}@odas.veenwacht.example.nl"
    assert msg["Reply-To"] == adres
    assert adres in msg.get_content()  # the words name it too, for a person who forwards


def test_the_confirmation_page_shows_the_zaak_address_and_the_inzien_link(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The indiener sees where to write and where to look, even when no mail arrives."""
    _capture_mail(monkeypatch)

    r = _submit(client, {})

    ref = re.search(r"zk-\d{5}", r.text).group()  # type: ignore[union-attr]
    token = zaak.load(zaak.find(ref)).token  # type: ignore[arg-type]
    assert f"{ref}@odas.veenwacht.example.nl" in r.text
    assert f'href="http://testserver/inzien-{token}"' in r.text


def test_the_confirmation_page_names_no_address_without_mail_capture(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A data dir that captures no mail offers no address to write to."""
    _capture_mail(monkeypatch)
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    del config["mailin"]
    write_config(tmp_path, config)

    r = _submit(client, {})

    assert "@odas.veenwacht.example.nl" not in r.text
    assert "/inzien-" in r.text  # the link does not depend on mail


def test_a_mailed_link_is_https_when_the_proxy_terminated_tls(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The link an indiener gets mailed opens over https, not over a redirect."""
    values = _capture_values(monkeypatch)

    _submit(client, {"X-Forwarded-Proto": "https"})

    assert values["inzien_url"].startswith("https://")


def test_a_mailed_link_stays_http_without_a_proxy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A developer running the app directly gets the scheme they actually used."""
    values = _capture_values(monkeypatch)

    _submit(client, {})

    assert values["inzien_url"].startswith("http://")


def test_a_new_form_submission_waits_for_the_team(client: TestClient, tmp_path: Path) -> None:
    """The Opvolgen column shows a flag: the automatic confirmation answers nothing."""
    r = client.post(
        "/indienen",
        data={
            "titel": "Kapvergunning boom",
            "omschrijving": "Zorgen over een vergunning.",
            "contact_naam": "A. de Vries",
            "contact_email": "a@example.org",
            "mail_toestemming": "nee",
        },
    )
    ref = re.search(r"zk-\d{5}", r.text).group()  # type: ignore[union-attr]
    folder = zaak.find(ref)
    assert folder is not None

    z = zaak.load(folder)
    assert [e.direction for e in z.log_entries] == ["IN"]  # the submission, and nothing after it
    assert z.log_entries[0].frontmatter["onderwerp"] == "indiening"
    assert z.frontmatter["opvolgen"] == "ja"  # a new submission needs the team
    assert "bevestiging verstuurd naar a@example.org" in z.history  # the send is in the audit
    assert "Bevestiging verstuurd naar a@example.org." in z.log_entries[0].body


def test_a_confirmation_that_cannot_go_out_is_recorded_in_the_zaak(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The indiening entry says why the link did not go out; the flag is set."""
    from odas import mail

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise mail.MailError("relay.example.nl nam het bericht niet aan.")

    monkeypatch.setattr(mail, "send", refuse)

    r = client.post(
        "/indienen",
        data={
            "titel": "Kapvergunning boom",
            "omschrijving": "Zorgen over een vergunning.",
            "contact_naam": "A. de Vries",
            "contact_email": "a@example.org",
            "mail_toestemming": "nee",
        },
    )
    assert r.status_code == 200  # the zaak stands: the submission is not thrown away
    ref = re.search(r"zk-\d{5}", r.text).group()  # type: ignore[union-attr]
    folder = zaak.find(ref)
    assert folder is not None

    z = zaak.load(folder)
    assert [e.direction for e in z.log_entries] == ["IN"]  # no entry hides the submission
    assert "Bevestiging niet verstuurd naar a@example.org" in z.log_entries[0].body
    assert "relay.example.nl nam het bericht niet aan." in z.log_entries[0].body
    assert z.frontmatter["opvolgen"] == "ja"  # a new submission needs the team


def _box(html: str) -> str:
    """The text the description box starts with."""
    return html.split('name="omschrijving"')[1].split("</textarea>")[0]


def test_the_public_form_states_the_scope_without_a_click(client: TestClient) -> None:
    """A person reads what the organisation does and does not do on the open page."""
    form = client.get("/indienen").text

    assert "<details" not in form  # no section to open
    assert "Geen NIMBY-zaken" in form
    assert "Wij nemen geen zaken over." in form
    assert "een expert uit ons netwerk aanbevelen" in form


def test_the_description_box_starts_with_the_questions(client: TestClient) -> None:
    """An indiener reads the questions in the box and writes the answers under them."""
    box = _box(client.get("/indienen").text)

    assert "Welk probleem speelt er en wat is het belang voor de natuur?" in box
    assert "Loopt er al een procedure?" in box
    assert "Is er al een advocaat of adviseur betrokken?" in box
    assert "\n\n" in box  # a blank line under each question, to write the answer in


def test_a_refused_form_shows_the_typed_text_back(client: TestClient) -> None:
    """The questions give way to the answer; a refusal never throws that answer away."""
    r = client.post("/indienen", data={"titel": "", "omschrijving": "Mijn eigen tekst."})

    assert "Mijn eigen tekst." in _box(r.text)
    assert "Welk probleem speelt er" not in _box(r.text)


def test_the_public_form_asks_which_kind_of_indiener_writes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Vereniging, stichting or burger; the answer stands in the zaak."""
    _capture_mail(monkeypatch)
    form = client.get("/indienen").text
    assert 'value="vereniging"' in form and 'value="stichting"' in form
    assert 'value="burger"' in form

    r = client.post(
        "/indienen",
        data={
            "titel": "Kap in het bos",
            "omschrijving": "Zorgen.",
            "contact_naam": "A. de Vries",
            "contact_email": "a@example.org",
            "mail_toestemming": "nee",
            "indiener_soort": "vereniging",
        },
    )
    ref = re.search(r"zk-\d{5}", r.text).group()  # type: ignore[union-attr]
    folder = zaak.find(ref)
    assert folder is not None
    assert zaak.load(folder).frontmatter["indiener_soort"] == "vereniging"


def test_the_public_form_asks_the_deadline_per_procedure(client: TestClient) -> None:
    """The deadline names its own procedure, in the words of the person who writes it."""
    form = client.get("/indienen").text

    assert "Termijn" in form and "voor welke procedure(s)?" in form
    assert 'name="termijn_soort"' in form  # free text, so no list of procedures
    assert '<select name="termijn_soort"' not in form


def test_the_upload_block_asks_for_the_decision_and_the_own_documents(client: TestClient) -> None:
    """The documents of the bevoegd gezag and the own zienswijze, bezwaar or beroep."""
    form = client.get("/indienen").text

    assert "Besluit en uw documenten" in form
    assert "uw zienswijze, bezwaar, beroep" in form
    assert "max 150 MB per bestand" in form
