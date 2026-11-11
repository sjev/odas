"""A data dir that ships its own intake form: `.app/intake.html`.

The page is the organisation's own. It posts one JSON part, `zaak`, and the
files under `documenten`. The server reads that JSON the way it reads the
builtin form: only the declared public fields, the same checks, the same mail.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import EXAMPLE_DATA, VEENWACHT_ZAKEN
from fastapi.testclient import TestClient

from odas import zaak
from odas.intake_answers import TITEL_MAX, TOO_LONG

_VELDEN = {
    "contact_naam": "A. de Vries",
    "contact_email": "a@example.org",
    "indiener_soort": "stichting",
    "naam_organisatie": "Stichting Berk",
    "mail_toestemming": "nee",
}


def _capture_mail(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[str]]]:
    """Record what would be sent, without a transport. Returns the (name, to) log."""
    sent: list[tuple[str, list[str]]] = []

    def fake_send(name: str, to: list[str], **kwargs: Any) -> None:
        sent.append((name, to))

    monkeypatch.setattr("odas.mail.send_template", fake_send)
    return sent


def _payload(**over: Any) -> dict[str, tuple[None, str]]:
    body = {"titel": "Kap in het park", "body": "## Hulpvraag\n\nZorgen.", "velden": _VELDEN}
    return {"zaak": (None, json.dumps({**body, **over}))}


def test_a_stranger_opens_the_form_the_data_dir_ships(client: TestClient) -> None:
    """The page at /indienen is the organisation's own file, as it is."""
    own = (EXAMPLE_DATA / "veenwacht" / ".app" / "intake.html").read_text(encoding="utf8")

    r = client.get("/indienen")
    assert r.text == own
    assert "naam_organisatie" in r.text  # the one field this form adds


def test_the_site_root_is_the_intake_form(client: TestClient) -> None:
    """A stranger who opens the site sees the form, the same page as /indienen."""
    assert client.get("/").text == client.get("/indienen").text


def test_a_data_dir_form_creates_a_zaak_from_its_json(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A form the data dir ships posts one JSON part; the zaak holds its fields and its body."""
    sent = _capture_mail(monkeypatch)
    payload = {
        "titel": "Kap in het park",
        "body": "## Hulpvraag\n\nZorgen over een vergunning.",
        "velden": {**_VELDEN, "behandelaar": "iemand"},
    }
    r = client.post("/indienen", files={"zaak": (None, json.dumps(payload))})
    folder = zaak.find(r.json()["ref"])
    assert folder is not None
    z = zaak.load(folder)
    assert z.frontmatter["naam_organisatie"] == "Stichting Berk"
    assert z.frontmatter["behandelaar"] == ""  # the team assigns it, so the form cannot set it
    assert z.body.strip() == "## Hulpvraag\n\nZorgen over een vergunning."
    assert sent == [("intake_bevestiging", ["a@example.org"])]


def test_a_json_submission_names_each_empty_field_and_creates_nothing(
    client: TestClient,
) -> None:
    """The page gets the keys back, so it can mark each field a person left empty."""
    velden = {k: v for k, v in _VELDEN.items() if k != "contact_email"}

    r = client.post("/indienen", files=_payload(titel="", velden=velden))
    assert r.status_code == 422
    assert r.json()["errors"] == {
        "titel": "Dit veld is verplicht.",
        "contact_email": "Dit veld is verplicht.",
    }
    assert len(zaak.list_ids()) == VEENWACHT_ZAKEN


def test_a_json_submission_with_an_unknown_value_is_refused(client: TestClient) -> None:
    """A value the type does not know never reaches disk, whatever the page sends."""
    r = client.post("/indienen", files=_payload(velden={**_VELDEN, "indiener_soort": "bedrijf"}))
    assert r.status_code == 422
    assert "bedrijf" in r.json()["errors"]["_"]
    assert len(zaak.list_ids()) == VEENWACHT_ZAKEN


def test_a_part_that_is_not_json_is_refused(client: TestClient) -> None:
    r = client.post("/indienen", files={"zaak": (None, "{niet af")})
    assert r.status_code == 422
    assert r.json()["errors"]["_"]  # a Dutch message, for the page to show
    assert len(zaak.list_ids()) == VEENWACHT_ZAKEN


def test_the_documents_of_a_json_submission_land_as_one_log_entry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The files travel next to the JSON part and arrive like the builtin form's."""
    _capture_mail(monkeypatch)
    files: list[tuple[str, tuple[str | None, bytes | str, str]]] = [
        ("zaak", (None, _payload()["zaak"][1], "application/json")),
        ("documenten", ("besluit.pdf", b"%PDF-1.4 fake", "application/pdf")),
    ]
    r = client.post("/indienen", files=files)
    folder = zaak.find(r.json()["ref"])
    assert folder is not None
    entry = zaak.load(folder).log_entries[0]
    assert entry.frontmatter["onderwerp"] == "indiening"
    assert (folder / "log" / entry.name / "besluit.pdf").read_bytes() == b"%PDF-1.4 fake"


def test_a_json_null_counts_as_an_empty_answer(client: TestClient) -> None:
    """A page that sends null for an answer left empty gets the same message as for ""."""
    r = client.post("/indienen", files=_payload(titel=None))
    assert r.status_code == 422
    assert r.json()["errors"] == {"titel": "Dit veld is verplicht."}  # never the text "None"
    assert len(zaak.list_ids()) == VEENWACHT_ZAKEN


def test_a_json_answer_that_is_not_text_is_refused(client: TestClient) -> None:
    """A list or a number is not text; the zaak never holds its Python spelling."""
    r = client.post("/indienen", files=_payload(velden={**_VELDEN, "naam_organisatie": ["x"]}))
    assert r.status_code == 422
    assert r.json()["errors"]["_"]
    assert len(zaak.list_ids()) == VEENWACHT_ZAKEN


def test_a_json_submission_answers_the_zaak_address_and_the_inzien_link(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The data dir's page can show where to write and where to look."""
    _capture_mail(monkeypatch)

    answer = client.post("/indienen", files=_payload()).json()

    token = zaak.load(zaak.find(answer["ref"])).token  # type: ignore[arg-type]
    assert answer["adres"] == f"{answer['ref']}@odas.veenwacht.example.nl"
    assert answer["inzien_url"] == f"http://testserver/inzien-{token}"


def test_an_indiener_who_answers_ja_gives_consent_on_the_zaak(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The team sees on the zaak that the indiener agreed to mail about the work and donations."""
    _capture_mail(monkeypatch)
    page = client.get("/indienen").text
    assert "over haar werk en met verzoeken om steun" in page  # the text the indiener agrees to

    r = client.post("/indienen", files=_payload(velden={**_VELDEN, "mail_toestemming": "ja"}))
    z = zaak.load(zaak.find(r.json()["ref"]))  # type: ignore[arg-type]
    assert z.frontmatter["mail_toestemming"] == "ja"


def test_an_indiener_must_answer_the_mail_question(client: TestClient) -> None:
    """No answer is no consent, so the page asks for ja or nee before it sends."""
    velden = {k: v for k, v in _VELDEN.items() if k != "mail_toestemming"}

    r = client.post("/indienen", files=_payload(velden=velden))
    assert r.status_code == 422
    assert r.json()["errors"] == {"mail_toestemming": "Dit veld is verplicht."}
    assert len(zaak.list_ids()) == VEENWACHT_ZAKEN


def test_a_titel_longer_than_the_limit_is_refused(client: TestClient) -> None:
    """The titel names the zaak in lists and mail; a whole story there is sent back."""
    r = client.post("/indienen", files=_payload(titel="x" * (TITEL_MAX + 1)))
    assert r.status_code == 422
    assert r.json()["errors"] == {"titel": TOO_LONG}
    assert len(zaak.list_ids()) == VEENWACHT_ZAKEN
