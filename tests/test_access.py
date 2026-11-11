"""Who may see and change what.

One rule: `is_team or email in z.toegang`. The team group opens every zaak; the
`toegang:` field opens one. That field *is* the grant, so a type without one
carries no grant. Whoever gets in may edit: read-only sharing is the token link,
which needs no account at all.

An **indiener** has no login: they hold a capability token that opens one zaak's
public subset.

A zaak a viewer holds no grant on answers **404, not 403**: the number of zaken
we hold is itself not theirs to learn.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import (
    DOSSIER,
    GRANTEE,
    LEEG,
    ZAAK,
    ZAAK_FOLDER,
    fake_directory,
    fake_users,
    token_of,
    use_example_data,
    write_config,
)
from fastapi.testclient import TestClient

from odas import index_write, zaak
from odas.config import Config

UNGRANTED = "zk-93810"  # an example zaak GRANTEE is not named in


# ── Sessions ──────────────────────────────────────────────────────────────────


def test_the_session_token_round_trips_the_email_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cookie proves one thing: which account this browser holds. Access is a
    separate question, asked of the directory on every request."""
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    from odas.auth import create_session_token, verify_session_token

    result = verify_session_token(create_session_token("jan@example.org"))
    assert result == {"email": "jan@example.org"}


@pytest.mark.parametrize("bad", ["garbage", ""])
def test_an_unsigned_token_is_no_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    from odas.auth import verify_session_token

    assert verify_session_token(bad) is None


def test_team_membership_derives_from_the_configured_oidc_group() -> None:
    """One group decides one boolean. Everyone else gets in through a zaak's toegang."""
    from odas.auth import is_team_member

    team = "veenwacht_team"
    assert is_team_member([team], team)
    assert is_team_member(["externe_experts", team], team)
    assert not is_team_member(["externe_experts"], team)
    assert not is_team_member([], team)


def test_no_session_redirects_to_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    from odas.app import app

    with TestClient(app) as c:
        r = c.get("/zaken", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"].startswith("/login")


def test_a_search_engine_is_told_to_stay_out_without_a_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crawler gets a plain no, not a login page it asks for again and again."""
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    from odas.app import create_app

    with TestClient(create_app()) as c:
        r = c.get("/robots.txt", follow_redirects=False)
        assert r.status_code == 200
        assert r.text == "User-agent: *\nDisallow: /\n"


@pytest.mark.parametrize(
    "path", ["/favicon.ico", "/apple-touch-icon-120x120-precomposed.png", "/wp-login.php", "/.env"]
)
def test_a_path_the_app_does_not_serve_is_a_404_not_a_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """Browsers, phones and scanners ask for these on their own; no person is signing in."""
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    from odas.app import create_app

    with TestClient(create_app()) as c:
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 404
        assert "location" not in r.headers


def test_an_unknown_zaak_still_asks_for_a_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stranger cannot tell a zaak that exists from one that does not."""
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    from odas.app import create_app

    with TestClient(create_app()) as c:
        r = c.get("/zaken/zk-00000", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"].startswith("/login")


def test_a_signed_in_user_with_no_grant_sees_an_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Authentication is not authorisation. Nothing is granted, so nothing is listed."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    fake_users(monkeypatch, others=("nobody@example.org",))
    from odas.app import create_app
    from odas.auth import COOKIE_NAME, create_session_token

    with TestClient(create_app()) as c:
        c.cookies.set(COOKIE_NAME, create_session_token("nobody@example.org"))
        r = c.get("/zaken", follow_redirects=False)
        assert r.status_code == 200
        assert f"/zaken/{ZAAK}" not in r.text
        assert f"/zaken/{UNGRANTED}" not in r.text


def test_the_json_api_is_locked_outside_test_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    from odas.app import app

    payload = {"titel": "Test", "omschrijving": "Test.", "velden": {"contact_email": "x@e.org"}}
    with TestClient(app) as c:
        assert c.post("/api/zaken", json=payload).status_code == 403


# ── The user directory ────────────────────────────────────────────────────────
#
# pocket-id is the directory, and it is read fresh. A list that cannot be fetched
# is not replaced by an older one: a viewer must never wonder whether the names
# in front of them are the names that hold access now.


def test_an_unreachable_directory_never_serves_the_previous_user_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When pocket-id cannot be reached the app says so, instead of showing who
    held access the last time it answered."""
    from odas import pocketid
    from odas.users import User

    first = [User(first_name="Tess", last_name="Berg", email="tess@example.org", is_team=True)]
    answered = [first]

    def fetch() -> list[User]:
        if answered:
            return answered.pop()
        raise ConnectionError("pocket-id unreachable")

    monkeypatch.setattr(pocketid, "_fetch_users", fetch)

    assert [u.email for u in pocketid.list_users()] == ["tess@example.org"]
    with pytest.raises(ConnectionError):
        pocketid.list_users()  # the second call must not replay the first


def test_leaving_the_team_group_takes_effect_on_the_very_next_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A colleague removed from the team group in pocket-id loses access at once.
    The session they already hold carries no answer, so there is nothing to wait out."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    from odas.app import create_app
    from odas.auth import COOKIE_NAME, create_session_token
    from odas.users import User

    email = "tess@example.org"
    directory = [User(first_name="Tess", last_name="Berg", email=email, is_team=True)]
    monkeypatch.setattr("odas.users.load_users", lambda: list(directory))

    with TestClient(create_app()) as c:
        c.cookies.set(COOKIE_NAME, create_session_token(email))
        assert c.get(f"/zaken/{UNGRANTED}").status_code == 200  # the team opens every zaak

        directory[0] = User(first_name="Tess", last_name="Berg", email=email, is_team=False)
        assert c.get(f"/zaken/{UNGRANTED}").status_code == 404  # same cookie, no grant left


def test_an_unreachable_directory_answers_503_rather_than_an_empty_desk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusing to answer is not the same as answering "no grant". Silently
    emptying the list would read as data loss, which is the worse lie."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    from odas.app import create_app
    from odas.auth import COOKIE_NAME, create_session_token

    def unreachable() -> list[object]:
        raise ConnectionError("pocket-id unreachable")

    monkeypatch.setattr("odas.users.load_users", unreachable)

    with TestClient(create_app()) as c:
        c.cookies.set(COOKIE_NAME, create_session_token("tess@example.org"))
        r = c.get("/zaken")
        assert r.status_code == 503
        assert "niet bereikbaar" in r.text  # it says what is wrong, not "geen zaken"


def test_a_token_link_still_opens_while_the_directory_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An indiener holds no account, so nothing about them is in pocket-id. Their
    link must not depend on it being up."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    from odas.app import create_app

    token = token_of(ZAAK)

    def unreachable() -> list[object]:
        raise ConnectionError("pocket-id unreachable")

    monkeypatch.setattr("odas.users.load_users", unreachable)

    with TestClient(create_app()) as c:
        r = c.get(f"/inzien-{token}")
        assert r.status_code == 200
        assert ZAAK in r.text


def test_a_data_dir_that_declares_no_directory_simply_lists_nobody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not configured and not reachable are different answers. A deployment that
    never had a user directory is not having an outage."""
    use_example_data("veenwacht", tmp_path, monkeypatch)  # declares an oidc issuer, carries no key
    from odas import pocketid

    assert pocketid.list_users() == []


def test_a_local_run_without_sign_in_never_asks_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the sign-in skipped, the editor opens on a real data dir whose
    directory refuses this machine. The dev user is the only person offered."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    monkeypatch.setenv("ODAS_TEST_MODE", "1")
    from odas import pocketid
    from odas.users import User

    def refused() -> list[User]:
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(pocketid, "_fetch_users", refused)
    from odas.app import create_app

    with TestClient(create_app()) as c:
        r = c.get(f"/zaken/{ZAAK}/bewerken")
    assert r.status_code == 200
    assert "test@example.com" in r.text  # the toegang picker offers the dev user


def test_the_editor_opens_when_the_directory_holds_an_account_without_an_email(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One address-less account in pocket-id must not close the edit form for
    everybody. The colleagues who do have an address are still offered."""
    from odas import pocketid

    fake_directory(
        tmp_path,
        monkeypatch,
        {
            "firstName": "Anna",
            "lastName": "Bakker",
            "email": "anna@example.nl",
            "userGroups": [{"name": "veenwacht_team"}],
        },
        {"firstName": "Kiosk", "lastName": None, "email": None, "userGroups": []},
    )
    monkeypatch.setattr("odas.users.load_users", pocketid.list_users)  # read the wire, not a stub

    r = client.get(f"/zaken/{ZAAK}/bewerken")
    assert r.status_code == 200
    assert "anna@example.nl" in r.text  # the toegang picker rendered the directory


def test_a_directory_change_shows_up_on_the_very_next_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing is remembered between calls, so a colleague added in pocket-id is
    there immediately and one removed is gone immediately."""
    from odas import pocketid
    from odas.users import User

    directory = [User(first_name="Tess", last_name="Berg", email="tess@example.org")]
    monkeypatch.setattr(pocketid, "_fetch_users", lambda: list(directory))

    assert [u.email for u in pocketid.list_users()] == ["tess@example.org"]
    directory.append(User(first_name="Ravi", last_name="Nair", email="ravi@example.org"))
    assert [u.email for u in pocketid.list_users()] == ["tess@example.org", "ravi@example.org"]
    directory.clear()
    assert pocketid.list_users() == []


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("tess@example.org", True),  # in the team group
        ("TESS@Example.org", True),  # the address is matched case-insensitively
        ("ravi@example.org", False),  # an account, but outside the team group
        ("stranger@example.org", False),  # no account at all
        ("", False),  # an empty identity is in no group
    ],
)
def test_team_membership_is_answered_from_the_directory(
    monkeypatch: pytest.MonkeyPatch, email: str, expected: bool
) -> None:
    from odas import pocketid, users
    from odas.users import User

    # Faked at the pocket-id call itself, so the question travels the real path:
    # is_team -> load_users -> pocketid.list_users.
    monkeypatch.setattr(
        pocketid,
        "_fetch_users",
        lambda: [
            User(first_name="Tess", last_name="Berg", email="tess@example.org", is_team=True),
            User(first_name="Ravi", last_name="Nair", email="ravi@example.org", is_team=False),
        ],
    )
    assert users.is_team(email) is expected


def test_an_unreachable_directory_makes_team_membership_unanswerable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The question is not answered "no". A removed grant and an outage must not
    look the same to the caller."""
    from odas import users

    def unreachable() -> list[users.User]:
        raise ConnectionError("pocket-id unreachable")

    monkeypatch.setattr("odas.users.load_users", unreachable)
    with pytest.raises(ConnectionError):
        users.is_team("tess@example.org")


# ── Access predicates ─────────────────────────────────────────────────────────
#
# The same rule the routes enforce, asked as a plain question about a viewer and a
# zaak. A test states the rule; the route only translates the answer into a status
# code.


def test_a_team_member_may_view_any_zaak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import access

    folder = zaak.find(UNGRANTED)
    assert folder is not None
    viewer = access.Viewer(email="anyone@example.org", is_team=True)
    assert access.may_access(viewer, zaak.load(folder))


def test_a_grantee_may_view_only_a_zaak_that_names_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `toegang:` field is the grant, so one viewer gets opposite answers."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import access

    granted, ungranted = zaak.find(ZAAK), zaak.find(UNGRANTED)
    assert granted is not None and ungranted is not None
    viewer = access.Viewer(email=GRANTEE)
    assert access.may_access(viewer, zaak.load(granted))
    assert not access.may_access(viewer, zaak.load(ungranted))


def test_a_signed_in_user_with_no_grant_may_view_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import access

    folder = zaak.find(ZAAK)
    assert folder is not None
    assert not access.may_access(access.Viewer(email="nobody@example.org"), zaak.load(folder))


def test_an_anonymous_viewer_may_view_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty toegang list and an empty email must never meet and match."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import access

    folder = zaak.find(UNGRANTED)  # its toegang: field is empty
    assert folder is not None
    assert zaak.load(folder).toegang == set()
    assert not access.may_access(access.Viewer(), zaak.load(folder))


@pytest.mark.parametrize("is_team", [True, False])
def test_only_a_team_member_may_create_a_zaak(is_team: bool) -> None:
    from odas import access

    assert access.may_create(access.Viewer(email="x@example.org", is_team=is_team)) is is_team


def test_an_edit_is_attributed_to_the_signed_in_email() -> None:
    """The audit line names one identity, the same one the access rule reads."""
    from odas import access

    assert access.actor(access.Viewer(email=GRANTEE)) == GRANTEE
    assert access.actor(access.Viewer(email="j.jansen@example.org", is_team=True)) == (
        "j.jansen@example.org"
    )


# ── The grantee's scope ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", f"/zaken/{ZAAK}", 200),  # granted: may read
        ("GET", f"/zaken/{ZAAK}/bewerken", 200),  # and may edit: access is not read-only
        ("GET", f"/zaken/{UNGRANTED}", 404),  # no grant: does not exist, as far as they know
        ("GET", f"/zaken/{UNGRANTED}/bewerken", 404),
        ("GET", "/zaken/zk-00000/bewerken", 404),  # so an unknown ref answers the same
    ],
)
def test_grantee_route_permissions(
    grantee_client: TestClient, method: str, path: str, expected: int
) -> None:
    assert grantee_client.request(method, path).status_code == expected


def test_a_grantee_may_edit_a_zaak_that_names_them(grantee_client: TestClient) -> None:
    """Access means full edit. Read-only sharing is the token link, not a second role."""
    r = grantee_client.post(
        f"/zaken/{ZAAK}/bewerken", data={"status": "afgerond"}, follow_redirects=False
    )
    assert r.status_code == 303
    z = zaak.load(zaak.find(ZAAK))  # type: ignore[arg-type]
    assert z.frontmatter["status"] == "afgerond"
    assert GRANTEE in z.history  # the audit records who, by their e-mail


def test_the_index_shows_a_grantee_only_their_own_zaken(grantee_client: TestClient) -> None:
    """Not even the volume of our work leaks: the list is filtered, not just the pages."""
    body = grantee_client.get("/zaken").text
    assert f"/zaken/{ZAAK}" in body
    assert f"/zaken/{UNGRANTED}" not in body
    assert f"/zaken/{DOSSIER}" not in body


def test_a_grantee_works_through_the_log(grantee_client: TestClient) -> None:
    r = grantee_client.post(
        f"/zaken/{ZAAK}/log",
        data={
            "direction": "LOG",
            "entry_date": "2026-06-01",
            "onderwerp": "notitie",
            "body": "Mijn opmerking.",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    z = zaak.load(zaak.find(ZAAK))  # type: ignore[arg-type]
    added = [e for e in z.log_entries if e.datum == "2026-06-01"]
    assert [e.frontmatter["onderwerp"] for e in added] == ["notitie"]
    assert GRANTEE in z.history  # the audit records who, by their e-mail


def test_a_grantee_cannot_create_a_zaak(grantee_client: TestClient) -> None:
    assert grantee_client.post("/zaken", data={"titel": "Nieuwe zaak"}).status_code == 403


def test_a_grantee_deletes_the_zaak_that_names_them_and_no_other(
    grantee_client: TestClient,
) -> None:
    """Access is not a read-only tier, so it reaches the destructive verb too."""
    assert grantee_client.post(f"/zaken/{UNGRANTED}/verwijderen").status_code == 404

    r = grantee_client.post(f"/zaken/{ZAAK}/verwijderen", follow_redirects=False)
    assert r.status_code == 303
    assert zaak.find(ZAAK) is None
    assert GRANTEE in (Config().prullenbak_dir / ZAAK_FOLDER / "audit.log").read_text(
        encoding="utf8"
    )


def test_a_type_without_a_toegang_field_grants_nothing(
    grantee_client: TestClient,
) -> None:
    """The toegang field *is* the grant, so a type lacking one cannot carry access."""
    folder = zaak.find(ZAAK)
    assert folder is not None
    assert GRANTEE in zaak.load(folder).toegang

    index_write.update_index(
        folder, f"---\nid: {ZAAK}\nsoort: overleg\ntoegang: {GRANTEE}\n---\n\nx\n", by="jev"
    )
    assert zaak.load(folder).toegang == set()  # overleg declares no toegang field
    assert f"/zaken/{ZAAK}" not in grantee_client.get("/zaken").text
    assert grantee_client.get(f"/zaken/{ZAAK}").status_code == 404


def test_revoking_the_grant_takes_effect_on_the_next_request(grantee_client: TestClient) -> None:
    """The grant is read from disk per request; there is no cached access list."""
    assert grantee_client.get(f"/zaken/{ZAAK}").status_code == 200
    folder = zaak.find(ZAAK)
    assert folder is not None
    index_write.set_field(folder, "toegang", "", by="jev")
    assert grantee_client.get(f"/zaken/{ZAAK}").status_code == 404


# ── The indiener's capability token ───────────────────────────────────────────


def test_the_token_page_needs_no_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Indieners have no login, so the token pages must work with no cookie at all."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    from odas.app import create_app

    with TestClient(create_app()) as c:
        token = zaak.load(zaak.find(ZAAK)).token  # type: ignore[arg-type]
        assert c.get(f"/inzien-{token}").status_code == 200
        r = c.post(
            f"/inzien-{token}",
            data={"naam": "Piet", "onderwerp": "Vraag", "bericht": "Hoe staat het ervoor?"},
        )
        assert r.status_code == 200


def test_an_unknown_token_is_a_404(client: TestClient) -> None:
    assert client.get("/inzien-onbekend").status_code == 404


def test_a_token_resolves_to_exactly_one_zaak(client: TestClient) -> None:
    folder = zaak.find(ZAAK)
    assert folder is not None
    assert zaak.find_by_token(zaak.load(folder).token) == folder
    assert zaak.find_by_token("nope") is None
    assert zaak.find_by_token("") is None  # an empty token must never match


def test_the_token_page_is_a_public_subset(client: TestClient) -> None:
    """Internal notes, the audit trail and non-public fields never reach the indiener."""
    folder = zaak.find(ZAAK)
    assert folder is not None
    client.post(
        f"/zaken/{ZAAK}/log",
        data={"direction": "LOG", "entry_date": "2026-05-13", "body": "Geheime notitie."},
        follow_redirects=False,
    )
    body = client.get(f"/inzien-{zaak.load(folder).token}").text

    assert "Grubbenvorst" in body  # the public body is shown
    assert "Geheime notitie" not in body  # an internal LOG entry is not
    assert "zaak aangemaakt" not in body  # nor is the audit trail
    assert GRANTEE not in body  # nor a field that is not `public:`


def test_a_public_but_team_only_field_is_shown_and_not_editable(client: TestClient) -> None:
    """`status` is public: the indiener may read it, only the team may set it."""
    token = zaak.load(zaak.find(ZAAK)).token  # type: ignore[arg-type]
    assert 'name="status"' not in client.get(f"/inzien-{token}/bewerken").text

    r = client.post(
        f"/inzien-{token}/bewerken",
        data={"locatie": "Arcen", "status": "afgerond"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    fm = zaak.load(zaak.find(ZAAK)).frontmatter  # type: ignore[arg-type]
    assert fm["locatie"] == "Arcen"  # public and indiener-editable: accepted
    assert fm["status"] == "in_behandeling"  # posted anyway, ignored


def test_the_public_form_ignores_fields_it_does_not_offer(client: TestClient) -> None:
    folder = zaak.find(ZAAK)
    assert folder is not None
    index_write.set_field(folder, "behandelaar", "T. Team", by="jev")
    token = zaak.load(folder).token

    r = client.post(
        f"/inzien-{token}/bewerken",
        data={"fase": "zienswijze", "behandelaar": "Hacker"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    fm = zaak.load(folder).frontmatter
    assert fm["fase"] == "zienswijze"
    assert fm["behandelaar"] == "T. Team"


def test_a_type_with_no_public_editable_fields_has_no_edit_page(client: TestClient) -> None:
    token = zaak.load(zaak.find(DOSSIER)).token  # type: ignore[arg-type]
    assert client.get(f"/inzien-{token}/bewerken").status_code == 404
    assert client.post(f"/inzien-{token}/bewerken", data={"fase": "x"}).status_code == 404


def test_indiener_html_is_escaped_before_the_team_sees_it(client: TestClient) -> None:
    """Stored XSS: raw HTML from an untrusted reply must not reach the team UI live."""
    token = zaak.load(zaak.find(LEEG)).token  # type: ignore[arg-type]
    r = client.post(
        f"/inzien-{token}",
        data={
            "naam": "Piet",
            "onderwerp": "Vraag",
            "bericht": '<script>alert(1)</script><img src=x onerror="x">',
        },
    )
    assert r.status_code == 200

    shown = client.get(f"/zaken/{LEEG}").text.split('class="entry-text')[1].split("</div>")[0]
    assert "<script>" not in shown
    assert "<img" not in shown
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in shown  # a tag is shown as the text it is


def test_the_reply_token_is_never_written_into_the_case_record(client: TestClient) -> None:
    """A capability is not case information, so nothing that carries the case carries it.

    An agent reads the folder and an export leaves the building. Neither may hand
    on a string that opens the zaak to whoever reads it next.
    """
    folder = zaak.find(ZAAK)
    assert folder is not None
    token = zaak.load(folder).token
    assert token  # the link exists; it is only kept elsewhere

    assert token not in (folder / "index.md").read_text(encoding="utf8")
    assert token.encode() not in client.get(f"/zaken/{ZAAK}/export.zip").content


def test_a_grant_ends_when_the_account_leaves_the_directory(
    grantee_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A removed account loses its zaak at once, although its cookie is still valid."""
    assert "Mestverwerking" in grantee_client.get(f"/zaken/{ZAAK}").text

    fake_users(monkeypatch, "test@example.com")  # the directory no longer lists GRANTEE

    r = grantee_client.get(f"/zaken/{ZAAK}")
    assert r.status_code == 404
    assert "Mestverwerking" not in r.text


def test_a_grantee_cannot_add_a_zaak_they_may_not_open_to_a_dossier(
    grantee_client: TestClient,
) -> None:
    """A dossier shows its members, so a grantee may only group what they can open."""
    folder = _dossier_granted_to_grantee()

    r = grantee_client.post(
        f"/zaken/{DOSSIER}/relatie/zaken", data={"ref": LEEG}, follow_redirects=False
    )

    assert r.status_code == 422
    assert f"Onbekende zaak: {LEEG}." in r.text  # the same words as a zaak that does not exist
    assert LEEG not in zaak.load(folder).frontmatter["zaken"]


def _dossier_granted_to_grantee() -> Path:
    """DOSSIER, with a `toegang` field declared and naming GRANTEE."""
    config = yaml.safe_load(Config().data_dir.joinpath("config.yaml").read_text(encoding="utf8"))
    config["types"]["dossier"]["toegang"] = {"type": "toegang"}
    write_config(Config().root, config)
    folder = zaak.find(DOSSIER)
    assert folder is not None
    index_write.set_field(folder, "toegang", GRANTEE, by="jev")
    return folder


def test_the_raw_editor_cannot_add_a_zaak_the_grantee_may_not_open(
    grantee_client: TestClient,
) -> None:
    """The raw text writes the same field, so it meets the same rule."""
    folder = _dossier_granted_to_grantee()
    raw = (folder / "index.md").read_text(encoding="utf8")
    raw = raw.replace("  - zk-00001\n", f"  - zk-00001\n  - {LEEG}\n")

    r = grantee_client.post(
        f"/zaken/{DOSSIER}/bewerken",
        data={"mode": "raw", "raw_content": raw},
        follow_redirects=False,
    )

    assert r.status_code == 422
    assert LEEG not in zaak.load(folder).frontmatter["zaken"]


def test_the_picker_offers_a_grantee_only_the_zaken_they_may_open(
    grantee_client: TestClient,
) -> None:
    """Every title in the picker is a zaak the grantee could already read."""
    _dossier_granted_to_grantee()

    page = grantee_client.get(f"/zaken/{DOSSIER}/bewerken").text

    assert f'value="{LEEG}"' not in page
