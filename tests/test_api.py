from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from odas.users import User


def test_team_page_lists_pocketid_users(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = [
        User("Anna", "Bakker", "anna@example.nl", is_team=True),
        User("Marie", "Smit", "marie@example.nl", is_team=False),
    ]
    monkeypatch.setattr("odas.users.load_users", lambda: fake)
    r = client.get("/team")
    assert r.status_code == 200
    assert "Anna" in r.text
    assert "Marie" in r.text


def test_list_users_flags_the_team_group_and_keeps_everyone_else(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The directory feeds the toegang picker, so a user outside the team still belongs in it."""
    from conftest import fake_directory, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)  # payload uses the Veenwacht group names
    import odas.pocketid as pocketid

    fake_directory(
        tmp_path,
        monkeypatch,
        {
            "firstName": "Anna",
            "lastName": "Bakker",
            "email": "anna@example.nl",
            "userGroups": [{"name": "veenwacht_team"}],
        },
        {
            "firstName": "Marie",
            "lastName": "Smit",
            "email": "marie@example.nl",
            "userGroups": [{"name": "externe_experts"}],
        },
        {"firstName": "No", "lastName": "Group", "email": "no@example.nl", "userGroups": []},
    )

    users = pocketid.list_users()
    assert [(u.email, u.is_team) for u in users] == [
        ("anna@example.nl", True),
        ("marie@example.nl", False),  # no group of ours, but grantable and listed
        ("no@example.nl", False),
    ]


def test_an_account_without_an_email_address_is_not_in_the_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """pocket-id lets an account exist with no address. ODAS reads people by
    address, so such an account is not somebody it can list at all."""
    from conftest import fake_directory, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)
    import odas.pocketid as pocketid

    fake_directory(
        tmp_path,
        monkeypatch,
        {
            "firstName": "Anna",
            "lastName": "Bakker",
            "email": "anna@example.nl",
            "userGroups": [{"name": "veenwacht_team"}],
        },
        # A service account: pocket-id sends the key, with null for its value.
        {"firstName": "Kiosk", "lastName": None, "email": None, "userGroups": []},
    )

    assert [u.email for u in pocketid.list_users()] == ["anna@example.nl"]


# --- JSON /api (agent import) ---------------------------------------------------


def test_api_create_zaak(client: TestClient) -> None:
    r = client.post(
        "/api/zaken",
        json={
            "titel": "Kap van laanbomen",
            "omschrijving": "Gemeente wil 40 bomen kappen.",
            "velden": {
                "contact_naam": "B. Bos",
                "contact_email": "buurt@example.nl",
                "fase": "bezwaar",
            },
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("zk-")

    got = client.get(f"/zaken/{body['id']}")
    assert got.status_code == 200
    assert "Gemeente wil 40 bomen kappen" in got.text
    assert "B. Bos" in got.text  # the declared field landed as frontmatter, not as body text


def test_api_create_log_entry_with_attachment(client: TestClient) -> None:
    created = client.post(
        "/api/zaken",
        json={
            "titel": "Handhavingsverzoek",
            "omschrijving": "Illegale dam.",
            "velden": {"contact_email": "melder@example.nl"},
        },
    ).json()

    r = client.post(
        f"/api/zaken/{created['id']}/log",
        json={
            "direction": "IN",
            "datum": "2026-06-01",
            "onderwerp": "bezwaarschrift",
            "body": "Bijlage ontvangen.",
            "attachments": {"rapport.txt": base64.b64encode(b"hallo").decode()},
        },
    )
    assert r.status_code == 201
    assert "2026-06-01-A-IN-bezwaarschrift" in r.json()["entry"]


def test_api_unknown_zaak_404(client: TestClient) -> None:
    r = client.post(
        "/api/zaken/zk-00000/log",
        json={"direction": "LOG", "datum": "2026-06-01", "onderwerp": "x"},
    )
    assert r.status_code == 404
