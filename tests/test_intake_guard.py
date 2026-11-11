"""The public intake refuses bots and stray files, and caps confirmation mail."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from odas import intake_guard, zaak

_FORM = {
    "titel": "Kap in het park",
    "omschrijving": "Zorgen.",
    "contact_naam": "A. de Vries",
    "contact_email": "a@example.org",
    "mail_toestemming": "nee",
}


@pytest.fixture
def client(client: TestClient, tmp_path: Path) -> TestClient:
    (tmp_path / ".app" / "intake.html").unlink(missing_ok=True)
    return client


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    log: list[list[str]] = []
    monkeypatch.setattr("odas.mail.send_template", lambda name, to, **kw: log.append(to))
    return log


@pytest.mark.parametrize("extra", [{"website": "http://spam"}, {"bedenktijd": "0.4"}])
def test_a_bot_makes_no_zaak(
    client: TestClient, sent: list[list[str]], extra: dict[str, str]
) -> None:
    before = zaak.list_ids()
    r = client.post("/indienen", data=_FORM | extra)
    assert r.status_code == 422
    assert intake_guard.REFUSED in r.text
    assert sent == []
    assert zaak.list_ids() == before


def test_a_human_pace_passes(client: TestClient, sent: list[list[str]]) -> None:
    r = client.post("/indienen", data=_FORM | {"website": "", "bedenktijd": "42.5"})
    assert r.status_code == 200
    assert sent == [["a@example.org"]]


def test_a_file_that_is_not_what_its_name_says_is_refused(
    client: TestClient, sent: list[list[str]]
) -> None:
    for name, content in [("virus.exe", b"MZ"), ("nep.pdf", b"MZ"), ("brief.txt", b"hallo")]:
        r = client.post("/indienen", data=_FORM, files=[("documenten", (name, content))])
        assert r.status_code == 422
        assert name in r.text
    assert sent == []


def test_one_address_gets_a_few_confirmations_a_day(
    client: TestClient, sent: list[list[str]]
) -> None:
    for _ in range(intake_guard.MAILS_PER_DAY + 2):
        assert client.post("/indienen", data=_FORM).status_code == 200
    assert len(sent) == intake_guard.MAILS_PER_DAY  # the zaken exist; the mail stops


def test_the_daily_allowance_comes_back() -> None:
    for _ in range(intake_guard.MAILS_PER_DAY):
        assert intake_guard.may_mail("B@example.org", now=0)
    assert not intake_guard.may_mail("b@example.org", now=1)
    assert intake_guard.may_mail("b@example.org", now=86401)
