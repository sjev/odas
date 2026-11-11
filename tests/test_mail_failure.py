"""A mail that did not go is announced in a popup, never only in a line of text.

The team reads the relay's own reason. An indiener reads a general message: the
reason can name the relay, and that is not for the public.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from conftest import LEEG, use_outbox
from fastapi.testclient import TestClient

from odas import intake_guard, log_write, mail, zaak

BASE = f"/zaken/{LEEG}"
REASON = "relay.example.nl nam het bericht niet aan."
INTAKE = {
    "titel": "Kapvergunning boom",
    "omschrijving": "Zorgen over een vergunning.",
    "contact_naam": "A. de Vries",
    "contact_email": "a@example.org",
    "mail_toestemming": "nee",
}


def _popup(html: str) -> str:
    """The text of the mail popup; empty when the page has none."""
    found = re.search(r'<dialog class="mail-alert".*?</dialog>', html, re.S)
    return found.group() if found else ""


def _refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise mail.MailError(REASON)

    monkeypatch.setattr(mail, "send", refuse)


@pytest.fixture
def builtin_form(client: TestClient, tmp_path: Path) -> TestClient:
    """The veenwacht data without its own form, so /indienen answers with a page."""
    (tmp_path / ".app" / "intake.html").unlink(missing_ok=True)
    return client


def test_a_log_entry_that_did_not_go_opens_a_popup_with_the_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Press Verstuur e-mail, the relay refuses, and a popup names its reason."""
    _refuse(monkeypatch)
    r = client.post(
        f"{BASE}/log",
        data={"direction": "UIT", "body": "Hallo.", "aan": "b@example.org", "action": "send"},
    )

    assert REASON in _popup(r.text)


def test_a_send_from_the_editor_that_did_not_go_opens_a_popup_with_the_reason(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same popup on the page that edits a saved entry."""
    folder = zaak.find(LEEG)
    assert folder is not None
    name = log_write.write_log_entry(
        folder, "UIT", "Uw hulpvraag", "Hallo.", aan="b@example.org"
    ).name
    _refuse(monkeypatch)
    r = client.post(
        f"{BASE}/log/{name.removesuffix('.md')}/bewerken",
        data={"body": "Hallo.", "aan": "b@example.org", "direction": "UIT", "action": "send"},
    )

    assert REASON in _popup(r.text)


def test_a_confirmation_that_did_not_go_opens_a_general_popup(
    builtin_form: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The indiener reads that no mail came, and keeps the kenmerk; never the relay's words."""
    _refuse(monkeypatch)
    r = builtin_form.post("/indienen", data=INTAKE)

    popup = _popup(r.text)
    assert "geen bevestiging" in popup
    assert REASON not in r.text
    assert "U ontvangt een bevestiging" not in r.text  # the page does not promise it either
    assert re.search(r"zk-\d{5}", r.text)  # the kenmerk is still on the page


def test_a_confirmation_held_back_by_the_day_limit_opens_the_same_popup(
    builtin_form: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The day limit is a mail that did not go, too."""
    monkeypatch.setattr(intake_guard, "may_mail", lambda to: False)
    r = builtin_form.post("/indienen", data=INTAKE)

    assert "geen bevestiging" in _popup(r.text)


def test_a_confirmation_that_went_opens_no_popup(builtin_form: TestClient, tmp_path: Path) -> None:
    """A sent confirmation leaves the page as it was."""
    use_outbox(tmp_path)
    r = builtin_form.post("/indienen", data=INTAKE)

    assert _popup(r.text) == ""
    assert "U ontvangt een bevestiging" in r.text


def test_an_own_form_reads_the_general_message_in_the_answer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A data dir's own form gets the same words, to show in its own popup."""
    _refuse(monkeypatch)
    velden = {**INTAKE, "indiener_soort": "stichting", "naam_organisatie": "Stichting Berk"}
    own = {"titel": "Kap in het park", "body": "Zorgen.", "velden": velden}
    answer = client.post("/indienen", files={"zaak": (None, json.dumps(own))}).json()

    assert "geen bevestiging" in answer["melding"]
    assert REASON not in answer["melding"]
