"""A dossier is a zaak. It has `soort: dossier` and a `zaken` field, and that
is the whole difference -- same folder store, same URL space, same log.

Membership is written by the picker route alone, never by the edit form, so
saving a dossier can never silently drop its members.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import (
    ZAAK,
    ZAAK_TITEL,
    create_dossier,
    eml_files,
    post_log,
    use_outbox,
    write_config,
)
from fastapi.testclient import TestClient
from test_overzicht import rows

from odas import index_write, web_helpers, zaak
from odas.zaak_view import relation_zaken


def test_a_dossier_is_created_through_the_same_form_and_store(
    client: TestClient, tmp_path: Path
) -> None:
    r = client.post(
        "/zaken",
        data={"titel": "Veegproject Maasplassen", "soort": "dossier"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    folder = zaak.find(r.headers["location"].rsplit("/", 1)[-1])
    assert folder is not None
    assert folder.parent == tmp_path / "zaken"  # one folder store, no dossiers/
    assert "zaak aangemaakt" in (folder / "audit.log").read_text(encoding="utf8")

    z = zaak.load(folder)
    assert z.soort == "dossier"
    assert z.titel == "Veegproject Maasplassen"
    assert z.frontmatter["zaken"] == ""


def test_the_soort_select_offers_every_declared_type(client: TestClient) -> None:
    r = client.get("/zaken")
    assert '<select name="soort">' in r.text
    assert '<option value="dossier"' in r.text


def test_a_dossier_has_its_own_page(client: TestClient) -> None:
    """A dossier is a soort, so it gets the page every soort gets, holding only its own."""
    dossiers = client.get("/zaken?soort=dossier").text
    assert "gedempte sloten" in dossiers  # a dossier in the example data
    assert ZAAK_TITEL not in dossiers  # a hulpvraag belongs on the other page


def test_the_row_follows_the_type(client: TestClient) -> None:
    """A dossier declares no status and no termijn, so those cells stay empty."""
    dossier_rows = "\n".join(rows(client.get("/zaken?soort=dossier").text))
    assert "badge" not in dossier_rows  # the status badge
    assert 'data-label="Termijn"' not in dossier_rows  # an empty cell carries no label

    hulpvraag_rows = "\n".join(rows(client.get("/zaken?soort=hulpvraag").text))
    assert "badge" in hulpvraag_rows
    assert "2026.06.26" in hulpvraag_rows  # ZAAK's termijn


# ── Membership ────────────────────────────────────────────────────────────────


def test_linking_a_zaak_writes_only_the_dossier(client: TestClient) -> None:
    ds_id = create_dossier(client)
    member_index = zaak.find(ZAAK) / "index.md"  # type: ignore[operator]
    before = member_index.read_bytes()

    r = client.post(
        f"/zaken/{ds_id}/relatie/zaken",
        data={"ref": ZAAK, "actie": "toevoegen"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert zaak.load(zaak.find(ds_id)).frontmatter["zaken"] == ZAAK  # type: ignore[arg-type]
    assert member_index.read_bytes() == before  # a member never learns it was linked


def test_a_zaak_can_be_unlinked_again(client: TestClient) -> None:
    ds_id = create_dossier(client)
    for actie in ("toevoegen", "verwijderen"):
        client.post(f"/zaken/{ds_id}/relatie/zaken", data={"ref": ZAAK, "actie": actie})
    assert zaak.load(zaak.find(ds_id)).frontmatter["zaken"] == ""  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("ref", "message"),
    [("zk-00000", "Onbekende zaak"), (ZAAK, "zit al in dit dossier")],
)
def test_a_bad_link_is_refused_with_a_422(client: TestClient, ref: str, message: str) -> None:
    ds_id = create_dossier(client)
    client.post(f"/zaken/{ds_id}/relatie/zaken", data={"ref": ZAAK, "actie": "toevoegen"})
    r = client.post(f"/zaken/{ds_id}/relatie/zaken", data={"ref": ref, "actie": "toevoegen"})
    assert r.status_code == 422
    assert message in r.text


def test_a_type_without_a_zaken_field_has_no_relation_route(client: TestClient) -> None:
    r = client.post(f"/zaken/{ZAAK}/relatie/zaken", data={"ref": "zk-1", "actie": "toevoegen"})
    assert r.status_code == 404


def test_the_picker_offers_what_is_not_already_a_member(client: TestClient) -> None:
    ds_id = create_dossier(client)
    r = client.get(f"/zaken/{ds_id}/bewerken")
    assert '<select name="ref"' in r.text
    assert f'<option value="{ZAAK}"' in r.text
    assert "Mestverwerking Grubbenvorst · In behandeling" in r.text  # titel plus status badge

    client.post(f"/zaken/{ds_id}/relatie/zaken", data={"ref": ZAAK, "actie": "toevoegen"})
    assert f'<option value="{ZAAK}"' not in client.get(f"/zaken/{ds_id}/bewerken").text


def test_saving_the_form_does_not_wipe_the_members(client: TestClient) -> None:
    """The picker is the only writer, so a plain save must leave `zaken` alone."""
    ds_id = create_dossier(client, "Veegproject")
    client.post(f"/zaken/{ds_id}/relatie/zaken", data={"ref": ZAAK, "actie": "toevoegen"})

    r = client.post(
        f"/zaken/{ds_id}/bewerken",
        data={"mode": "form", "id": ds_id, "titel": "Veegproject", "body": "Tekst."},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert zaak.load(zaak.find(ds_id)).frontmatter["zaken"] == ZAAK  # type: ignore[arg-type]


def test_a_member_that_no_longer_exists_renders_as_an_error_row(client: TestClient) -> None:
    """A dangling ref is shown, not hidden: the folder is the truth, warts and all."""
    ds_id = create_dossier(client)
    folder = zaak.find(ds_id)
    assert folder is not None
    index_write.set_field(folder, "zaken", "zk-99999", by="jev")

    assert relation_zaken(zaak.load(folder))[0].error == "Onbekende zaak."
    assert "zk-99999" in client.get(f"/zaken/{ds_id}").text


def test_a_dossier_lists_its_members_once(client: TestClient) -> None:
    """The page renders the refs as links, so the raw `zaken` value gets no second row."""
    ds_id = create_dossier(client)
    client.post(f"/zaken/{ds_id}/relatie/zaken", data={"ref": ZAAK, "actie": "toevoegen"})
    assert client.get(f"/zaken/{ds_id}").text.count(f"/zaken/{ZAAK}?") == 1


def test_a_dossier_page_maps_its_members_locations(client: TestClient) -> None:
    ds_id = create_dossier(client)
    for ref, latlon in ((ZAAK, "51.3,6.1"), ("zk-93810", "51.2,6.0")):
        folder = zaak.find(ref)
        assert folder is not None
        index_write.set_field(folder, "locatie", latlon, by="jev")
        client.post(f"/zaken/{ds_id}/relatie/zaken", data={"ref": ref, "actie": "toevoegen"})

    assert 'data-latlon="51.3,6.1; 51.2,6.0"' in client.get(f"/zaken/{ds_id}").text
    token = zaak.load(zaak.find(ds_id)).token  # type: ignore[arg-type]
    assert 'data-latlon="51.3,6.1; 51.2,6.0"' in client.get(f"/inzien-{token}").text


def test_a_dossier_maps_its_members_wherever_the_type_puts_the_location(
    client: TestClient, tmp_path: Path
) -> None:
    """The map follows the latlon type; nothing keys on a field named `locatie`."""
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    hulpvraag = config["types"]["hulpvraag"]
    hulpvraag["plek"] = hulpvraag.pop("locatie")
    write_config(tmp_path, config)

    ds_id = create_dossier(client)
    folder = zaak.find(ZAAK)
    assert folder is not None
    index_write.set_field(folder, "plek", "51.3,6.1", by="jev")
    client.post(f"/zaken/{ds_id}/relatie/zaken", data={"ref": ZAAK, "actie": "toevoegen"})

    assert 'data-latlon="51.3,6.1"' in client.get(f"/zaken/{ds_id}").text


# ── The rest of a zaak's behaviour applies unchanged ──────────────────────────


def test_a_dossier_keeps_a_log_like_any_zaak(client: TestClient) -> None:
    ds_id = create_dossier(client)
    r = client.post(
        f"/zaken/{ds_id}/log",
        data={
            "direction": "LOG",
            "entry_date": "2026-07-09",
            "onderwerp": "Strategie overleg",
            "body": "Notities van het overleg.",
        },
        files={"documenten": ("notitie.pdf", b"%PDF-1.4", "application/pdf")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "Strategie overleg" in client.get(f"/zaken/{ds_id}").text

    entry = "2026-07-09-A-LOG-strategie-overleg"
    assert client.get(f"/zaken/{ds_id}/log/{entry}/bijlage/notitie.pdf").status_code == 200
    assert client.get(f"/zaken/{ds_id}/log/{entry}/bewerken").status_code == 200


def test_a_dossier_token_opens_a_public_view(client: TestClient) -> None:
    ds_id = create_dossier(client, "Veegproject Maasplassen")
    folder = zaak.find(ds_id)
    assert folder is not None
    client.post(f"/zaken/{ds_id}/relatie/zaken", data={"ref": ZAAK, "actie": "toevoegen"})
    post_log(client, f"/zaken/{ds_id}", onderwerp="Geheim", body="Geheime notitie.")

    token = zaak.load(folder).token
    assert web_helpers.token_folder(token) == folder
    body = client.get(f"/inzien-{token}").text
    assert "Veegproject Maasplassen" in body
    assert 'name="onderwerp"' in body  # the reply form is embedded
    assert "Geheime notitie" not in body  # an internal LOG entry stays internal
    assert f"/zaken/{ds_id}/bewerken" not in body  # no edit link
    assert f"/zaken/{ZAAK}" not in body  # no team-only links to the members


def test_a_reply_on_a_dossier_needs_no_behandelaar_to_notify(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ds_id = create_dossier(client)
    folder = zaak.find(ds_id)
    assert folder is not None
    outbox = use_outbox(tmp_path)

    r = client.post(
        f"/inzien-{zaak.load(folder).token}",
        data={"naam": "Piet", "onderwerp": "Mijn reactie", "bericht": "Aanvullende informatie."},
        follow_redirects=False,
    )
    assert r.status_code == 303

    entries = zaak.load(folder).log_entries
    assert [(e.direction, e.frontmatter["onderwerp"]) for e in entries] == [("IN", "Mijn reactie")]
    assert eml_files(outbox) == []  # a dossier declares no behandelaar, so nobody to notify


def test_the_old_dossier_urls_still_resolve(client: TestClient) -> None:
    """Those URLs are in already-sent mail, so they must keep working."""
    ds_id = create_dossier(client)
    r = client.get(f"/dossiers/{ds_id}", follow_redirects=False)
    assert r.status_code == 308
    assert r.headers["location"] == f"/zaken/{ds_id}"

    r = client.get(f"/dossiers/{ds_id}/log/x/bijlage/y.pdf", follow_redirects=False)
    assert r.headers["location"] == f"/zaken/{ds_id}/log/x/bijlage/y.pdf"
    assert client.get("/dossiers/", follow_redirects=False).headers["location"] == "/zaken"
