"""What a zaak is on disk, and what survives a round trip through the tool.

The example data in `tests/data/` is the subject: if these tests pass, the
files a jurist can read, edit and back up are exactly what ODAS understands.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import (
    DOSSIER,
    LEEG,
    OVERLEG,
    VEENWACHT_ZAKEN,
    VMS_ZAKEN,
    ZAAK,
    ZAAK_TITEL,
    leave_behind,
    use_example_data,
)
from fastapi.testclient import TestClient

from odas import index_write, log_write, schema, zaak, zaak_create
from odas.appconfig import field_for_key, type_fields
from odas.fields import StatusField

# ── The example data itself ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(("profile", "count"), [("veenwacht", VEENWACHT_ZAKEN), ("vms", VMS_ZAKEN)])
def test_the_example_data_is_valid_for_its_profile(
    profile: str, count: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each profile's example data is a data dir it accepts whole -- no problems, nothing skipped."""
    use_example_data(profile, tmp_path, monkeypatch)
    assert zaak.check_all() == []
    assert len(zaak.list_all()) == count


def test_every_example_zaak_loads_with_the_fields_of_its_soort(client: TestClient) -> None:
    for z in zaak.list_all():
        assert not z.error
        assert z.titel  # never blank: falls back to the ref
        assert set(z.fields) >= {"id", "soort", "titel", "aangemaakt"}  # base keys injected


def test_a_dossier_is_a_zaak_with_a_zaken_field(client: TestClient) -> None:
    z = zaak.load(zaak.find(DOSSIER))  # type: ignore[arg-type]
    assert z.soort == "dossier"
    assert z.frontmatter["zaken"] == "zk-93810, zk-00001, zk-42817"
    assert z.badge is None  # a dossier declares no status, so it has no badge


def test_an_overleg_carries_a_status_and_an_eigenaar_and_nothing_else(
    client: TestClient,
) -> None:
    """An internal discussion is a whole zaak with almost no fields."""
    z = zaak.load(zaak.find(OVERLEG))  # type: ignore[arg-type]
    assert z.soort == "overleg"
    assert set(z.frontmatter) == {
        "id",
        "soort",
        "titel",
        "aangemaakt",
        "gewijzigd",
        "status",
        "eigenaar",
    }
    assert z.behandelaar == "m.kuipers@example.org"  # resolved by kind, not by key name
    assert not z.token  # no reply_token declared, so no /inzien- page


def test_reading_a_zaak_writes_nothing(client: TestClient) -> None:
    """Viewing is not a mutation: no lazy back-filling of tokens or defaults."""
    folder = zaak.find(ZAAK)
    assert folder is not None
    before = (folder / "index.md").read_bytes()
    assert client.get(f"/zaken/{ZAAK}").status_code == 200
    assert (folder / "index.md").read_bytes() == before


# ── Frontmatter: dump and parse ───────────────────────────────────────────────


def test_dump_writes_every_declared_field_in_declaration_order() -> None:
    fields = type_fields("procedure")
    text = schema.dump({"id": "zk-1", "locatie": "X"}, "Body.", fields)

    frontmatter = text.split("---\n")[1]
    keys = [line.split(":")[0] for line in frontmatter.splitlines() if not line.startswith(" ")]
    expected = [k for key, f in fields.items() for k in f.disk_keys(key)]
    assert keys == expected  # order on disk is the declaration order
    assert "ext_ref:" in text  # an unset field is still listed, empty
    assert "nieuw | in_behandeling" in text  # options documented inline as a comment


def test_a_multi_key_field_writes_its_disk_keys_and_not_its_own_name() -> None:
    text = schema.dump({"id": "zk-1"}, "", type_fields("procedure"))
    assert "termijn_datum:" in text and "termijn_soort:" in text
    assert "\ntermijn:" not in text


def test_dump_preserves_keys_outside_the_schema() -> None:
    """A schema change must not silently drop data already on disk."""
    text = schema.dump({"id": "zk-1", "oud_veld": "waarde"}, "Body.", type_fields("procedure"))
    assert "oud_veld: waarde" in text
    assert "onbekend veld" in text
    assert schema.parse(text)[0]["oud_veld"] == "waarde"


def test_a_multi_field_round_trips_as_a_yaml_block() -> None:
    text = schema.dump(
        {"id": "ds-1", "zaken": "zk-00001, zk-42817"}, "Body.", type_fields("dossier")
    )
    assert "  - zk-00001" in text and "  - zk-42817" in text
    fm, body = schema.parse(text)
    assert fm["zaken"] == "zk-00001, zk-42817"  # a list reads back as CSV in memory
    assert body == "Body."


def test_an_empty_multi_field_stays_one_line() -> None:
    text = schema.dump({"id": "ds-1", "zaken": ""}, "", type_fields("dossier"))
    assert "zaken:" in text
    assert "  -" not in text


# ── Derived state ─────────────────────────────────────────────────────────────


def test_status_field_owns_the_badge(client: TestClient) -> None:
    """`status: status` needs no options: the type carries the generic vocabulary."""
    f = type_fields("hulpvraag")["status"]
    assert isinstance(f, StatusField)
    assert f.values == ["nieuw", "in_behandeling", "wacht", "afgerond"]
    assert f.badge("in_behandeling") == ("In behandeling", "status-progress")
    assert f.badge("verzonnen") == ("verzonnen", "")  # never hide a value we cannot label

    assert zaak.load(zaak.find(ZAAK)).badge == ("In behandeling", "status-progress")  # type: ignore[arg-type]


def test_termijn_is_one_declared_field_over_two_disk_keys(client: TestClient) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    index_write.update_fields(
        folder, {"termijn_datum": "2026-09-01", "termijn_soort": "bezwaar"}, by="jev"
    )
    t = zaak.load(folder).termijn
    assert t is not None and (t.due, t.kind) == ("2026-09-01", "bezwaar")

    fields = type_fields("hulpvraag")
    assert field_for_key(fields, "termijn_datum") is fields["termijn"]  # else it reads as unknown


def _drop_line(folder: Path, key: str) -> None:
    """Strip a frontmatter key, the way an older or hand-made index.md would lack it."""
    index = folder / "index.md"
    kept = [x for x in index.read_text("utf8").splitlines() if not x.startswith(f"{key}:")]
    index.write_text("\n".join(kept), encoding="utf8")


def test_soort_defaults_to_the_first_declared_type(client: TestClient) -> None:
    """A zaak without a `soort:` line predates the registry; it reads as the default."""
    folder = zaak.find(LEEG)
    assert folder is not None
    _drop_line(folder, "soort")
    z = zaak.load(folder)
    assert z.soort == "hulpvraag"
    assert "status" in z.fields  # the hulpvraag declaration, not just the base fields


def test_titel_falls_back_to_the_ref(client: TestClient) -> None:
    """An unmigrated index.md has no titel; the ref stands in until one is set."""
    folder = zaak.find(LEEG)
    assert folder is not None
    _drop_line(folder, "titel")
    assert zaak.load(folder).titel == LEEG
    index_write.set_field(folder, "titel", "Woo schutterij", by="jev")
    assert zaak.load(folder).titel == "Woo schutterij"


def test_the_folder_name_is_frozen_at_creation(client: TestClient) -> None:
    folder = zaak.find(ZAAK)
    assert folder is not None
    name_before = folder.name
    index_write.set_field(folder, "titel", "Nieuwe naam", by="jev")

    assert folder.name == name_before  # the slug never follows the titel
    assert "Nieuwe naam" in client.get(f"/zaken/{ZAAK}").text
    assert "Nieuwe naam" in client.get("/zaken").text
    assert ZAAK_TITEL not in client.get("/zaken").text


def test_retyping_via_raw_text_preserves_undeclared_keys(client: TestClient) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    index_write.update_index(
        folder,
        f"---\nid: {LEEG}\nsoort: dossier\ntitel: Veegzaak\neigen_veld: blijft staan\n---\n\nOmgezet.\n",
        by="jev",
    )
    z = zaak.load(folder)
    assert z.soort == "dossier"
    assert "zaken" in z.fields  # now validated against the dossier declaration
    assert z.frontmatter["eigen_veld"] == "blijft staan"
    assert "Soort gewijzigd: hulpvraag → dossier" in z.history


def test_retyping_to_an_unknown_soort_is_rejected(client: TestClient) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    with pytest.raises(ValueError, match="Onbekend type"):
        index_write.update_index(folder, f"---\nid: {LEEG}\nsoort: verzonnen\n---\n\nx\n", by="jev")


# ── Validation: what the schema refuses ───────────────────────────────────────


def test_an_empty_required_field_is_refused(client: TestClient) -> None:
    fields = type_fields("hulpvraag")
    with pytest.raises(ValueError, match=r"verplicht|Referentie"):
        schema.validate({"id": "", "soort": "hulpvraag"}, fields)


def test_a_value_outside_the_enum_is_refused(client: TestClient) -> None:
    """Enums are a closed vocabulary: a typo must not reach disk as a new status."""
    fields = type_fields("hulpvraag")
    with pytest.raises(ValueError, match="verzonnen"):
        schema.validate({"id": "zk-1", "status": "verzonnen"}, fields)


def test_a_termijn_soort_is_free_text(client: TestClient) -> None:
    """A person names the deadline in their own words, so any wording is kept."""
    folder = zaak.find(LEEG)
    assert folder
    index_write.update_fields(
        folder,
        {"termijn_datum": "2026-09-01", "termijn_soort": "verdaging beslistermijn"},
        by="jev",
    )
    assert zaak.load(folder).termijn.kind == "verdaging beslistermijn"  # type: ignore[union-attr]


def test_saving_an_unknown_status_through_the_writer_is_refused(client: TestClient) -> None:
    """The writer is the funnel, so the refusal reaches the caller, not the file."""
    folder = zaak.find(LEEG)
    assert folder is not None
    before = (folder / "index.md").read_bytes()
    with pytest.raises(ValueError):
        index_write.set_field(folder, "status", "verzonnen", by="jev")
    assert (folder / "index.md").read_bytes() == before  # refused means unchanged


# ── Serialization: values that could break the file ───────────────────────────


@pytest.mark.parametrize(
    "titel",
    [
        "Bezwaar: fase 2",  # a colon would start a nested mapping
        "- Woo-verzoek",  # a leading dash would read as a list item
        "  ingesprongen  ",  # leading and trailing space would be eaten
        "{niet} [echt]",  # flow-style openers
        "Kap # 12",  # a hash would start a comment
    ],
)
def test_a_titel_that_looks_like_yaml_survives_a_round_trip(titel: str) -> None:
    """Quoting is what keeps a jurist's own words from re-parsing as structure."""
    text = schema.dump({"id": "zk-1", "titel": titel}, "Body.", type_fields("procedure"))
    assert schema.parse(text)[0]["titel"] == titel.strip()


def test_a_yaml_date_and_a_null_read_back_as_text(client: TestClient) -> None:
    """Frontmatter is text in memory: YAML's own types are coerced, never passed on."""
    folder = zaak.find(LEEG)
    assert folder is not None
    (folder / "index.md").write_text(
        f"---\nid: {LEEG}\nsoort: hulpvraag\ntermijn_datum: 2026-09-01\nbehandelaar: null\n---\n\nx\n",
        encoding="utf8",
    )
    fm = schema.parse((folder / "index.md").read_text("utf8"))[0]
    assert fm["termijn_datum"] == "2026-09-01"
    assert fm["behandelaar"] == ""


# ── Timestamps and tokens the system writes ───────────────────────────────────


def test_aangemaakt_is_an_iso_timestamp_in_utc_to_the_second(client: TestClient) -> None:
    from datetime import datetime

    z = zaak_create.create_minimal("Nieuwe zaak", "hulpvraag")
    stamp = z.frontmatter["aangemaakt"]
    assert datetime.fromisoformat(stamp) is not None
    assert len(stamp) == 25 and stamp.endswith("+00:00")  # 2026-08-07T12:33:33+00:00, in UTC


def test_every_new_zaak_gets_its_own_reply_token(client: TestClient) -> None:
    """The token is the capability: two zaken sharing one would share access."""
    tokens = {zaak_create.create_minimal(f"Zaak {n}", "hulpvraag").token for n in range(3)}
    assert len(tokens) == 3
    assert all(tokens)


def test_the_audit_log_records_who_changed_what_and_when(client: TestClient) -> None:
    """audit.log is part of the on-disk contract: a jurist reads it without the app."""
    import re

    folder = zaak.find(LEEG)
    assert folder is not None
    index_write.set_field(folder, "status", "afgerond", by="jev")

    last = (folder / "audit.log").read_text("utf8").strip().splitlines()[-1]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} \[jev\] .+", last), last
    assert "afgerond" in last


# ── The log: order lives in the name ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("2026-05-12-A-LOG-telefoon-indiener", ("2026-05-12", "A", "LOG", "telefoon-indiener")),
        ("2026-05-12-Z-UIT-x", ("2026-05-12", "Z", "UIT", "x")),
        # Letterless legacy names still parse: a hand-made file must not vanish.
        ("2026-05-12-LOG-telefoon", ("2026-05-12", "", "LOG", "telefoon")),
        ("2026-05-12-a-LOG-x", ("2026-05-12", "A", "LOG", "x")),  # lowercase reads as A
        ("2026-05-12-ZIJWAARTS-x", None),
        ("aantekeningen", None),
    ],
)
def test_parse_entry_name(stem: str, expected: tuple[str, str, str, str] | None) -> None:
    assert zaak.parse_entry_name(stem) == expected


def test_example_log_reads_back_in_name_order(client: TestClient) -> None:
    """zk-00001 has two multi-entry days; they must read A, B, C... by name alone."""
    entries = zaak.load(zaak.find(ZAAK)).log_entries  # type: ignore[arg-type]
    assert [(e.datum, e.letter) for e in entries] == sorted((e.datum, e.letter) for e in entries)
    day = [e.letter for e in entries if e.datum == "2026-06-07"]
    assert day == ["A", "B", "C", "D", "E", "F"]


def test_log_entries_sort_on_the_name_not_the_mtime(client: TestClient) -> None:
    """Order is data. Touching the files in reverse must not reshuffle the log."""
    folder = zaak.find(LEEG)
    assert folder is not None
    log_dir = folder / "log"
    log_dir.mkdir(exist_ok=True)
    for name in ("2026-05-12-C-LOG-derde", "2026-05-12-A-LOG-eerste", "2026-05-12-B-LOG-tweede"):
        (log_dir / f"{name}.md").write_text("---\n---\n\nx\n", encoding="utf8")
        os.utime(log_dir / f"{name}.md", (0, 1_700_000_000 - len(name)))

    assert [e.letter for e in zaak.scan_log(folder)] == ["A", "B", "C"]


def test_letterless_entry_sorts_first_and_is_reported(client: TestClient) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    log_dir = folder / "log"
    log_dir.mkdir(exist_ok=True)
    (log_dir / "2026-05-12-A-LOG-met.md").write_text("---\n---\n\nx\n", encoding="utf8")
    (log_dir / "2026-05-12-LOG-zonder.md").write_text("---\n---\n\nx\n", encoding="utf8")

    assert [e.slug for e in zaak.scan_log(folder)] == ["zonder", "met"]
    assert any("volgletter" in p.message for p in zaak.check_all())


def test_check_reports_a_key_the_soort_does_not_declare(client: TestClient) -> None:
    """A key left behind by a soort change is kept on disk, but check names it."""
    leave_behind(LEEG, "oud_kenmerk", "AB-12")

    [problem] = zaak.check_all()
    assert problem.path.endswith("/index.md")
    assert "oud_kenmerk" in problem.message


def test_new_entries_get_consecutive_letters(client: TestClient) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None
    for onderwerp in ("eerste", "tweede", "derde"):
        log_write.write_log_entry(folder, "LOG", onderwerp, "x", datum="2026-05-12")

    assert [e.letter for e in zaak.load(folder).log_entries] == ["A", "B", "C"]
    log_write.write_log_entry(folder, "LOG", "andere dag", "x", datum="2026-05-13")
    assert zaak.load(folder).log_entries[-1].letter == "A"  # a new date starts at A again


def test_an_attachment_in_the_example_data_is_reachable_from_its_entry(client: TestClient) -> None:
    entries = [e for e in zaak.load(zaak.find(ZAAK)).log_entries if e.attachments]  # type: ignore[arg-type]
    assert entries, "the example data should carry attachments"
    entry = entries[0]
    for rel in entry.attachments:
        assert (zaak.find(ZAAK) / rel).is_file()  # type: ignore[operator]
        r = client.get(f"/zaken/{ZAAK}/log/{entry.name}/bijlage/{rel.split('/')[-1]}")
        assert r.status_code == 200


def test_the_internal_owner_is_found_by_kind_and_not_by_key_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An organisation may call its caseworker anything; the model reads the kind."""
    from conftest import LOG_FIELDS, write_config

    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    write_config(tmp_path, {"types": {"zaak": {"dossierhouder": "user"}}, "fields": LOG_FIELDS})

    z = zaak_create.create_minimal("Ontgronding", "zaak")
    folder = zaak.find(z.ref)
    assert folder is not None
    index_write.set_field(folder, "dossierhouder", "Wim Bakker", by="test")

    assert zaak.load(folder).behandelaar == "Wim Bakker"  # not the literal key "behandelaar"


def test_a_zaak_keeps_its_reply_token_beside_the_index_and_not_inside_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A capability is not case information, so whatever reads the case misses it.

    The type declares the field under a name of its own choosing; the value is
    the same file either way, so the declaration is all the frontmatter holds.
    """
    from conftest import LOG_FIELDS, write_config

    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    write_config(tmp_path, {"types": {"zaak": {"leeslink": "reply_token"}}, "fields": LOG_FIELDS})

    z = zaak_create.create_minimal("Ontgronding", "zaak")
    folder = zaak.find(z.ref)
    assert folder is not None

    assert z.token  # the kind minted it at creation
    assert (folder / ".access-token").read_text(encoding="utf8").strip() == z.token
    assert (folder / ".access-token").stat().st_mode & 0o077 == 0  # nobody else may read it
    assert "leeslink" not in (folder / "index.md").read_text(encoding="utf8")

    found = zaak.find_by_token(z.token)
    assert found is not None and found.name == z.id


def test_a_zaak_with_a_very_long_titel_gets_a_short_folder_name(client: TestClient) -> None:
    """A titel may run on; the folder it makes stays short enough to copy anywhere."""
    titel = "Ontvangen aanvraag voor een wijziging van een omgevingsvergunning " * 4
    r = client.post("/zaken", data={"titel": titel}, follow_redirects=False)
    assert r.status_code == 303

    ref = r.headers["location"].split("/")[2]
    folder = zaak.find(ref)
    assert folder is not None
    assert len(folder.name) <= 109  # the 9 of "zk-NNNNN-", plus a 100 slug
    assert zaak.load(folder).titel == titel.strip()  # the full titel is still the state
