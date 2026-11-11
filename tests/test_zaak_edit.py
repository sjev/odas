"""Editing a zaak: the field form, and the raw frontmatter editor behind it.

Two ways in, one rule -- what the config says is editable is what changes. A
field the role may not edit is read back from disk, never from the form, so a
posted value for it is ignored rather than rejected.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml
from conftest import GRANTEE, LEEG, ZAAK, leave_behind, rename_field, write_config
from fastapi.testclient import TestClient
from markupsafe import escape

from odas import index_write, zaak


def retype(tmp_path: Path, **fields: object) -> None:
    """Add or replace fields on the hulpvraag type of the active data dir."""
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["types"]["hulpvraag"].update(fields)
    write_config(tmp_path, config)


def test_the_zaak_page_shows_a_key_the_schema_does_not_declare(client: TestClient) -> None:
    """A key left behind by a schema change is on the page, under its own name."""
    leave_behind(LEEG, "oud_kenmerk", "AB-12")
    r = client.get(f"/zaken/{LEEG}")
    assert "oud_kenmerk" in r.text
    assert "AB-12" in r.text


def test_the_zaak_page_shows_a_declared_field_nobody_filled_in(client: TestClient) -> None:
    """A field the organisation asked for gets a row even while it is empty."""
    r = client.get(f"/zaken/{LEEG}")
    assert "Contactpersoon naam" in r.text  # declared by hulpvraag, empty on this zaak


def test_a_key_the_schema_does_not_declare_survives_a_form_save(client: TestClient) -> None:
    """Editing a zaak never drops a key the app does not recognise."""
    leave_behind(LEEG, "oud_kenmerk", "AB-12")
    r = client.post(
        f"/zaken/{LEEG}/bewerken",
        data={"id": LEEG, "locatie": "Tegelen"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    after = zaak.load(zaak.find(LEEG))  # type: ignore[arg-type]
    assert after.frontmatter["oud_kenmerk"] == "AB-12"
    assert after.frontmatter["locatie"] == "Tegelen"


def test_the_edit_form_shows_the_zaak_as_it_is_on_disk(client: TestClient) -> None:
    r = client.get(f"/zaken/{ZAAK}/bewerken")
    assert r.status_code == 200
    assert "Grubbenvorst" in r.text
    assert ZAAK in r.text


def test_saving_the_form_persists_and_redirects(client: TestClient) -> None:
    r = client.post(
        f"/zaken/{LEEG}/bewerken",
        data={"id": LEEG, "locatie": "Tegelen", "body": "Aangepast."},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/zaken/{LEEG}"

    z = zaak.load(zaak.find(LEEG))  # type: ignore[arg-type]
    assert z.frontmatter["locatie"] == "Tegelen"
    assert z.body == "Aangepast."


def test_fields_of_one_group_stand_together_in_a_fieldset(client: TestClient) -> None:
    """The veenwacht config puts the contact fields in one group, so the form does too."""
    page = client.get(f"/zaken/{LEEG}/bewerken").text
    contact = page.split("<legend>Contact</legend>", 1)[1].split("</fieldset>", 1)[0]

    assert 'name="contact_naam"' in contact
    assert 'name="contact_email"' in contact
    assert 'name="termijn_datum"' not in contact  # a Procedure field, in its own fieldset
    assert 'name="toegang"' not in contact


def test_a_field_nobody_may_edit_stands_above_the_form_not_in_it(client: TestClient) -> None:
    """The stamps the system sets read as one line of facts, not as empty form rows."""
    page = client.get(f"/zaken/{LEEG}/bewerken").text
    facts = page.split('<p class="field-facts">', 1)[1].split("</p>", 1)[0]
    form = page.split('<div class="field-grid">', 1)[1]

    assert "Aangemaakt" in facts and "2026-07" in facts
    assert "Aangemaakt" not in form
    assert f'<input type="hidden" name="id" value="{LEEG}">' in page  # still travels with the save


def test_the_termijn_soort_is_typed_not_picked(client: TestClient) -> None:
    """The edit form offers a text box for the kind of deadline, not a fixed list."""
    r = client.get(f"/zaken/{LEEG}/bewerken")
    assert '<input type="text" name="termijn_soort"' in r.text
    assert '<select name="termijn_soort"' not in r.text


def test_an_invalid_value_is_refused_with_a_422(client: TestClient) -> None:
    r = client.post(f"/zaken/{LEEG}/bewerken", data={"id": LEEG, "status": "verzonnen"})
    assert r.status_code == 422
    assert "ongeldige waarde" in r.text.lower()


def test_the_form_cannot_touch_a_field_it_may_not_edit(client: TestClient) -> None:
    before = zaak.load(zaak.find(LEEG))  # type: ignore[arg-type]
    r = client.post(
        f"/zaken/{LEEG}/bewerken",
        data={
            "id": LEEG,
            "locatie": "Tegelen",
            "soort": "dossier",
            "aangemaakt": "1999-01-01T00:00:00",
            "reply_token": "gestolen",
            "body": before.body,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    after = zaak.load(zaak.find(LEEG))  # type: ignore[arg-type]
    for key in ("id", "soort", "aangemaakt", "reply_token"):
        assert after.frontmatter.get(key, "") == before.frontmatter.get(key, "")
    assert after.soort == "hulpvraag"  # retyping goes through raw text, not the form
    assert after.frontmatter["locatie"] == "Tegelen"


def test_the_raw_editor_round_trips_frontmatter_and_body(client: TestClient) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    index_write.update_index(
        folder,
        f"---\nid: {LEEG}\nlocatie: Arcen\n---\n\nNieuwe omschrijving.\n",
        by="jev",
    )
    z = zaak.load(folder)
    assert z.frontmatter["locatie"] == "Arcen"
    assert z.body == "Nieuwe omschrijving."
    assert z.frontmatter["id"] == LEEG
    assert "[jev] index bewerkt" in z.history


def test_a_typed_change_stamp_gives_way_to_the_real_one(client: TestClient) -> None:
    """The stamp says when the zaak last changed, so a hand-typed value never sticks."""
    folder = zaak.find(LEEG)
    assert folder is not None
    index_write.update_index(
        folder, f"---\nid: {LEEG}\ngewijzigd: 2020-01-01T00:00:00\n---\n\nx\n", by="jev"
    )

    z = zaak.load(folder)
    assert z.frontmatter["gewijzigd"].startswith(
        datetime.now(UTC).date().isoformat()
    )  # UTC on disk
    assert "Gewijzigd" not in z.history.splitlines()[-1]  # the stamp is no edit of its own


def test_the_zaak_page_shows_when_the_zaak_last_changed(client: TestClient) -> None:
    """The manual points at the date beside aangemaakt."""
    folder = zaak.find(LEEG)
    assert folder is not None
    index_write.set_field(folder, "status", "in_behandeling", by="jev")

    r = client.get(f"/zaken/{LEEG}")
    assert f"gewijzigd {date.today():%Y.%m.%d}" in r.text


@pytest.mark.parametrize(
    ("bad_text", "why"),
    [
        (f"---\nid: {LEEG}\nno closing fence\n", "malformed frontmatter"),
        ("---\nid: zk-99999\n---\n\nx\n", "the id is the identity and cannot be retyped"),
    ],
)
def test_a_rejected_raw_edit_leaves_the_file_untouched(
    client: TestClient, bad_text: str, why: str
) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    before = (folder / "index.md").read_bytes()
    with pytest.raises(ValueError):
        index_write.update_index(folder, bad_text, by="jev")
    assert (folder / "index.md").read_bytes() == before, why


def test_unreadable_raw_text_comes_back_in_the_editor(client: TestClient) -> None:
    """Broken frontmatter reopens the editor with the typed text, never a crash."""
    r = client.post(
        f"/zaken/{LEEG}/bewerken",
        data={"mode": "raw", "raw_content": f"---\nid: {LEEG}\ntitel: [niet gesloten\n---\n\nx\n"},
    )
    assert r.status_code == 422
    assert "Ongeldige frontmatter" in r.text
    assert "[niet gesloten" in r.text  # the text the jurist typed is still in the box


def test_the_access_field_may_carry_any_name(client: TestClient, tmp_path: Path) -> None:
    """The grant is resolved by kind, so a data dir may call the field what it likes."""
    rename_field(tmp_path, "hulpvraag", "toegang", "machtiging")

    r = client.get(f"/zaken/{LEEG}/bewerken")
    assert f'name="machtiging" value="{GRANTEE}"' in r.text

    client.post(
        f"/zaken/{LEEG}/bewerken",
        data={"id": LEEG, "machtiging": GRANTEE},
        follow_redirects=False,
    )

    z = zaak.load(zaak.find(LEEG))  # type: ignore[arg-type]
    assert z.frontmatter["machtiging"] == GRANTEE
    assert z.toegang == {GRANTEE}
    assert z.frontmatter.get("toegang", "") == ""  # the old name is not written to


def test_setting_a_field_records_the_change_in_the_audit(client: TestClient) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    index_write.set_field(folder, "status", "in_behandeling", by="jev")

    z = zaak.load(folder)
    assert z.status == "in_behandeling"
    last = z.history.splitlines()[-1]
    assert "Status gewijzigd: nieuw → in_behandeling" in last
    assert last.startswith("20") and "[jev]" in last


@pytest.mark.parametrize(
    ("key", "value"),
    [("status", "verzonnen"), ("fase", "verzonnen")],
)
def test_setting_a_field_outside_its_options_is_refused(
    client: TestClient, key: str, value: str
) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    with pytest.raises(ValueError, match=key.split("_")[0]):
        index_write.set_field(folder, key, value, by="jev")


def test_a_type_can_declare_more_than_one_location(client: TestClient, tmp_path: Path) -> None:
    """A second latlon field is a config change, so both edit and save on their own."""
    retype(tmp_path, tweede_locatie={"type": "latlon", "editable": ["team"]})

    r = client.get(f"/zaken/{LEEG}/bewerken")
    assert 'id="locatie-input"' in r.text
    assert 'id="tweede_locatie-input"' in r.text

    client.post(
        f"/zaken/{LEEG}/bewerken",
        data={"id": LEEG, "locatie": "51.1,6.0", "tweede_locatie": "52.2,5.5"},
        follow_redirects=False,
    )
    z = zaak.load(zaak.find(LEEG))  # type: ignore[arg-type]
    assert z.frontmatter["locatie"] == "51.1,6.0"
    assert z.frontmatter["tweede_locatie"] == "52.2,5.5"


@pytest.mark.parametrize(
    ("value", "point"),
    [
        ("51.3,6.1", "51.3,6.1"),
        ("51°27'27.9\"N 5°38'54.1\"E", "51.45775,5.648361"),  # as Google Maps copies it
        ("10°30'S 20°15'W", "-10.5,-20.25"),  # south and west are negative
        ("hoek van de Dorpsstraat", None),
    ],
)
def test_only_a_location_that_reads_as_coordinates_gets_a_map(
    client: TestClient, value: str, point: str | None
) -> None:
    """Free text stays legal: an intake names a street before anyone pins it."""
    folder = zaak.find(LEEG)
    assert folder is not None
    index_write.set_field(folder, "locatie", value, by="jev")

    r = client.get(f"/zaken/{LEEG}")
    assert escape(value) in r.text  # the text shows as typed either way
    assert zaak.load(folder).frontmatter["locatie"] == value
    assert ('data-latlon="' in r.text) is (point is not None)
    if point:
        assert f'data-latlon="{point}"' in r.text


# ── Deleting a zaak ───────────────────────────────────────────────────────────


def _prullenbak() -> Path:
    from odas.config import Config

    return Config().prullenbak_dir


def test_a_deleted_zaak_leaves_the_overview(client: TestClient) -> None:
    """The zaak is gone from every page that lists it, and the rest stay."""
    r = client.post(f"/zaken/{LEEG}/verwijderen", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/zaken"

    body = client.get("/zaken").text
    assert f"/zaken/{LEEG}" not in body
    assert f"/zaken/{ZAAK}" in body
    assert client.get(f"/zaken/{LEEG}").status_code == 404


def test_a_deleted_zaak_is_readable_whole_in_the_prullenbak(client: TestClient) -> None:
    """A case file goes to the prullenbak, not a loose pile of files."""
    folder = zaak.find(ZAAK)
    assert folder is not None
    name, titel = folder.name, zaak.load(folder).frontmatter["titel"]

    client.post(f"/zaken/{ZAAK}/verwijderen")

    moved = _prullenbak() / name
    assert titel in (moved / "index.md").read_text(encoding="utf8")
    assert (moved / "audit.log").is_file()
    assert sorted(p.name for p in (moved / "log").iterdir())  # its entries came too


def test_the_delete_is_recorded_inside_the_deleted_folder(client: TestClient) -> None:
    """What happened stays attached to the thing it happened to."""
    folder = zaak.find(LEEG)
    assert folder is not None
    name = folder.name

    client.post(f"/zaken/{LEEG}/verwijderen")

    trail = (_prullenbak() / name / "audit.log").read_text(encoding="utf8")
    assert "verwijderd" in trail
    assert "test@example.com" in trail


def test_a_deleted_zaak_carries_its_own_prullenbak_along(client: TestClient) -> None:
    """The entry deleted yesterday is still recoverable after the case goes."""
    from odas import log_write

    folder = zaak.find(LEEG)
    assert folder is not None
    entry = log_write.create_log_entry(
        folder, "LOG", "2026-05-20", "---\nonderwerp: weg\n---\n\nNotitie.\n"
    ).stem
    client.post(f"/zaken/{LEEG}/log/{entry}/verwijderen")

    client.post(f"/zaken/{LEEG}/verwijderen")

    moved = _prullenbak() / folder.name / "prullenbak" / f"{entry}.md"
    assert "onderwerp: weg" in moved.read_text(encoding="utf8")


def test_the_confirm_step_names_the_zaak_and_counts_its_attachments(client: TestClient) -> None:
    """A person reads the title and the size of what goes before anything moves."""
    folder = zaak.find(ZAAK)
    assert folder is not None
    z = zaak.load(folder)
    count = sum(len(e.attachments) for e in z.log_entries)

    body = client.get(f"/zaken/{ZAAK}/verwijderen").text
    assert z.frontmatter["titel"] in body
    assert f"{count} bijlagen" in body
    assert zaak.find(ZAAK) is not None  # a look changes nothing


def test_only_the_edit_page_offers_to_delete_a_zaak(client: TestClient) -> None:
    """The zaak page is for reading the case, never for ending it."""
    action = f"/zaken/{LEEG}/verwijderen"
    assert action not in client.get(f"/zaken/{LEEG}").text
    assert action in client.get(f"/zaken/{LEEG}/bewerken").text


def test_the_export_leaves_the_prullenbak_out(client: TestClient) -> None:
    """An export is the case as it stands, not what someone took out of it."""
    import io
    import zipfile

    from odas import log_write

    folder = zaak.find(LEEG)
    assert folder is not None
    entry = log_write.create_log_entry(
        folder, "LOG", "2026-05-20", "---\nonderwerp: weg\n---\n\nNotitie.\n"
    ).stem
    client.post(f"/zaken/{LEEG}/log/{entry}/verwijderen")

    r = client.get(f"/zaken/{LEEG}/export.zip")
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert any(n.endswith("index.md") for n in names)
    assert not [n for n in names if "prullenbak" in n]


def test_a_type_without_a_status_has_no_badge(client: TestClient) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    index_write.update_index(folder, f"---\nid: {LEEG}\nsoort: dossier\n---\n\nx\n", by="jev")
    assert zaak.load(folder).badge is None
