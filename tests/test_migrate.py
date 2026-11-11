"""The migrations: the one-time zaak-base script, and the layout steps the app runs.

`scripts/migrate_to_types.py` stays outside the package (it must run on a bare VPS
with no venv), so it is loaded by path. The layout steps live in `odas.migrations`
and are imported.
"""

from __future__ import annotations

import importlib.util
import re
from email.message import EmailMessage
from pathlib import Path
from types import ModuleType

import pytest

from odas import dataversion, migrations, schema
from odas.migrations import (
    migrate_columns_to_org,
    migrate_flag_unanswered,
    migrate_stamp_gewijzigd,
    migrate_stamp_log_times,
    migrate_token_to_file,
)

ROOT = Path(__file__).resolve().parents[1]

OLD_ZAAK = """---
id: zk-00001
status: nieuw
fase: bezwaar
behandelaar: Hanna Geerts
locatie:
contact_naam:
contact_email:
termijn_soort:
termijn_datum:
experts:
aangemaakt: "2026-05-12T14:30:00"
reply_token: tok-zk-00001
---

Bewoners maken zich zorgen.
"""

OLD_DOSSIER = """---
id: ds-5256
titel: Vlietland
zaken:
  - zk-00001
aangemaakt: "2026-07-29T15:14:26"
reply_token: tok-ds-5256
---
"""


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migrate_to_types", ROOT / "scripts" / "migrate_to_types.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migrate_to_types = _load()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.fixture
def old_data(tmp_path: Path) -> Path:
    """An old-layout tree: one zaak, one dossier in its own store, one stray `old/`."""
    zaak = tmp_path / "zaken" / "zk-00001-mest-grubbenvorst"
    zaak.mkdir(parents=True)
    (zaak / "index.md").write_text(OLD_ZAAK, encoding="utf8")
    (zaak / "audit.log").write_text("2026-05-12 14:30 [jev] zaak aangemaakt\n", encoding="utf8")

    dossier = tmp_path / "dossiers" / "ds-5256-vlietland"
    (dossier / "log").mkdir(parents=True)
    (dossier / "index.md").write_text(OLD_DOSSIER, encoding="utf8")
    (dossier / "audit.log").write_text("2026-07-29 15:14 [jev] zaak aangemaakt\n", encoding="utf8")
    (dossier / "log" / "2026-07-30-LOG-notitie.md").write_text(
        '---\nonderwerp: notitie\naan:\ncc:\nbcc:\nverzonden: "2026-07-30T09:00:00"\n---\n\nHoi.\n',
        encoding="utf8",
    )
    # Two legacy entries on one date, plus one with the old field names, so the
    # letter hand-out and the key renames are both exercised.
    (zaak / "log").mkdir()
    (zaak / "log" / "2026-05-12-IN-bekendmaking").mkdir()
    (zaak / "log" / "2026-05-12-IN-bekendmaking" / "index.md").write_text(
        "---\nomschrijving: bekendmaking\ndatum: 2026-05-12\nnaar: a@b.nl\nbron: krant\n---\n\nX.\n",
        encoding="utf8",
    )
    (zaak / "log" / "2026-05-12-LOG-telefoon.md").write_text(
        "---\nonderwerp: telefoon\n---\n\nY.\n", encoding="utf8"
    )

    (tmp_path / "zaken" / "old" / "hv-1234-oude-zaak").mkdir(parents=True)
    return tmp_path


def test_dry_run_writes_nothing(old_data: Path) -> None:
    before = _snapshot(old_data)
    assert migrate_to_types.migrate(old_data, dry_run=True) > 0
    assert _snapshot(old_data) == before


def test_apply_stamps_zaak(old_data: Path) -> None:
    migrate_to_types.migrate(old_data, dry_run=False)
    text = (old_data / "zaken" / "zk-00001-mest-grubbenvorst" / "index.md").read_text("utf8")

    assert re.search(r"^soort: hulpvraag$", text, re.MULTILINE)
    assert re.search(r"^titel: Mest grubbenvorst$", text, re.MULTILINE)
    # New keys go in front, in base order. `aangemaakt` keeps its old position --
    # readers are order-insensitive and the first save rewrites canonically.
    keys = [m.group(1) for m in re.finditer(r"^(\w+):", text, re.MULTILINE)]
    assert keys[:3] == ["id", "soort", "titel"]


def test_apply_folds_dossier_into_zaken(old_data: Path) -> None:
    migrate_to_types.migrate(old_data, dry_run=False)
    moved = old_data / "zaken" / "ds-5256-vlietland"

    assert not (old_data / "dossiers" / "ds-5256-vlietland").exists()
    assert re.search(r"^soort: dossier$", (moved / "index.md").read_text("utf8"), re.MULTILINE)
    # An existing titel is kept, not overwritten by the slug.
    assert re.search(r"^titel: Vlietland$", (moved / "index.md").read_text("utf8"), re.MULTILINE)
    # The rename carries siblings along.
    assert (moved / "audit.log").is_file()
    assert (moved / "log" / "2026-07-30-A-LOG-notitie.md").is_file()


def test_apply_stamps_app_version(old_data: Path) -> None:
    migrate_to_types.migrate(old_data, dry_run=False)
    stamp = (old_data / ".app" / "app-version").read_text("utf8").strip()

    assert stamp == migrate_to_types.TARGET_VERSION


def test_idempotent(old_data: Path) -> None:
    migrate_to_types.migrate(old_data, dry_run=False, drop_old=True)
    after = _snapshot(old_data)
    assert migrate_to_types.migrate(old_data, dry_run=False, drop_old=True) == 0
    assert _snapshot(old_data) == after


def test_old_folder_kept_without_flag(old_data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    migrate_to_types.migrate(old_data, dry_run=False)
    assert (old_data / "zaken" / "old").is_dir()
    assert "SKIP old: pass --drop-old to delete" in capsys.readouterr().out


def test_drop_old_removes_it(old_data: Path) -> None:
    migrate_to_types.migrate(old_data, dry_run=False, drop_old=True)
    assert not (old_data / "zaken" / "old").exists()


def test_stray_dir_reported(old_data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (old_data / "zaken" / "rommel").mkdir()
    migrate_to_types.migrate(old_data, dry_run=True)
    assert "SKIP rommel: no index.md" in capsys.readouterr().out


def test_apply_letters_log_entries(old_data: Path) -> None:
    """Same-day entries get consecutive letters, in the mtime order the old reader used."""
    migrate_to_types.migrate(old_data, dry_run=False)
    log_dir = old_data / "zaken" / "zk-00001-mest-grubbenvorst" / "log"

    assert sorted(p.name for p in log_dir.iterdir()) == [
        "2026-05-12-A-IN-bekendmaking",
        "2026-05-12-B-LOG-telefoon.md",
    ]


def test_apply_renames_legacy_entry_fields(old_data: Path) -> None:
    """`omschrijving`/`naar` get their registered names; a redundant `datum` goes."""
    migrate_to_types.migrate(old_data, dry_run=False)
    log_dir = old_data / "zaken" / "zk-00001-mest-grubbenvorst" / "log"
    text = (log_dir / "2026-05-12-A-IN-bekendmaking" / "index.md").read_text("utf8")

    assert "onderwerp: bekendmaking" in text
    assert "aan: a@b.nl" in text
    assert "datum:" not in text  # the name carries the date
    assert "bron: krant" in text  # not ours to drop


def test_log_migration_is_idempotent(old_data: Path) -> None:
    migrate_to_types.migrate(old_data, dry_run=False)
    before = _snapshot(old_data)
    assert migrate_to_types.migrate(old_data, dry_run=False) == 0
    assert _snapshot(old_data) == before


# ── Layout 8 → 9: the reply token leaves the case record ──────────────────────


TOKEN_ZAAK = """---
id: zk-00001
soort: hulpvraag
titel: Mest
reply_token: AO4UxhJdGxODffaYzTnJkQ # systeem: capability-token voor reageerpagina
---

Bewoners maken zich zorgen.
"""


@pytest.fixture
def layout8(tmp_path: Path) -> Path:
    """A layout-8 tree: one live zaak and one trashed zaak, each with a token."""
    (tmp_path / ".app").mkdir(exist_ok=True)
    (tmp_path / ".app" / "config.yaml").write_text(
        "version: 8               # on-disk layout revision\ntypes: {}\n", encoding="utf8"
    )
    for store, ref in (("zaken", "zk-00001-mest"), ("prullenbak", "zk-00002-sloot")):
        folder = tmp_path / store / ref
        folder.mkdir(parents=True)
        (folder / "index.md").write_text(TOKEN_ZAAK, encoding="utf8")
    return tmp_path


def _migrate_token(root: Path, apply: bool) -> int:
    changed = migrate_token_to_file.main(root, apply=apply, key="reply_token")
    assert isinstance(changed, int)
    return changed


def test_the_token_migration_writes_nothing_on_a_dry_run(layout8: Path) -> None:
    before = _snapshot(layout8)
    assert _migrate_token(layout8, apply=False) > 0
    assert _snapshot(layout8) == before


def test_the_token_moves_into_its_own_file_beside_the_index(layout8: Path) -> None:
    """The value a reader could pipe into a mail is no longer in what they read."""
    _migrate_token(layout8, apply=True)
    folder = layout8 / "zaken" / "zk-00001-mest"

    assert (folder / ".access-token").read_text("utf8") == "AO4UxhJdGxODffaYzTnJkQ\n"
    assert (folder / ".access-token").stat().st_mode & 0o077 == 0  # nobody else may read it
    index = (folder / "index.md").read_text("utf8")
    assert "reply_token" not in index
    assert re.search(r"^titel: Mest$", index, re.MULTILINE)  # the rest of the record is untouched


def test_a_trashed_zaak_keeps_its_link_through_the_move(layout8: Path) -> None:
    """A restored zaak must still open on the link its indiener already holds."""
    _migrate_token(layout8, apply=True)
    trashed = layout8 / "prullenbak" / "zk-00002-sloot"
    assert (trashed / ".access-token").read_text("utf8") == "AO4UxhJdGxODffaYzTnJkQ\n"


def test_the_token_migration_stamps_the_layout_revision(layout8: Path) -> None:
    _migrate_token(layout8, apply=True)
    config = (layout8 / ".app" / "config.yaml").read_text("utf8")
    assert re.search(r"^version: 9\b", config, re.MULTILINE)


def test_the_token_migration_is_idempotent(layout8: Path) -> None:
    _migrate_token(layout8, apply=True)
    after = _snapshot(layout8)
    assert _migrate_token(layout8, apply=True) == 0
    assert _snapshot(layout8) == after


def _upgrade(root: Path, apply: bool) -> None:
    migrations.run(root, 8, dataversion.DATA_VERSION, apply=apply)


def test_one_upgrade_command_takes_a_layout_8_data_dir_to_the_layout_the_app_needs(
    layout8: Path,
) -> None:
    """The person runs one command and the app starts. They pick no script."""
    _upgrade(layout8, apply=True)

    config = (layout8 / ".app" / "config.yaml").read_text("utf8")
    assert f"version: {dataversion.DATA_VERSION}" in config
    folder = layout8 / "zaken" / "zk-00001-mest"
    assert (folder / ".access-token").read_text("utf8") == "AO4UxhJdGxODffaYzTnJkQ\n"
    assert "reply_token" not in (folder / "index.md").read_text("utf8")


def test_the_upgrade_keeps_the_old_text_of_every_file_it_changed(layout8: Path) -> None:
    """The backup holds the record as it was, so a bad run is reverted."""
    _upgrade(layout8, apply=True)

    saved = sorted((layout8 / ".backups").glob("*/zaken/zk-00001-mest/index.md"))
    assert len(saved) == 1
    assert "reply_token: AO4UxhJdGxODffaYzTnJkQ" in saved[0].read_text("utf8")


def test_the_upgrade_writes_nothing_until_it_is_told_to_apply(
    layout8: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _snapshot(layout8)
    _upgrade(layout8, apply=False)
    assert "Dry run" in capsys.readouterr().out
    assert _snapshot(layout8) == before


# ── Layout 9 → 10: every record carries its last change ─────────────────────


STAMP_ZAAK = """---
id: {ref}
soort: hulpvraag
titel: Mest
aangemaakt: "2026-05-12T14:30:00" # ISO tijdstip, niet wijzigen
status: nieuw
---

Bewoners maken zich zorgen.
"""


@pytest.fixture
def layout9(tmp_path: Path) -> Path:
    """A layout-9 tree: one zaak with a trail, one trashed zaak with none."""
    (tmp_path / ".app").mkdir(exist_ok=True)
    (tmp_path / ".app" / "config.yaml").write_text(
        "version: 9               # on-disk layout revision\ntypes: {}\n", encoding="utf8"
    )
    for store, name in (("zaken", "zk-00001-mest"), ("prullenbak", "zk-00002-sloot")):
        folder = tmp_path / store / name
        folder.mkdir(parents=True)
        (folder / "index.md").write_text(STAMP_ZAAK.format(ref=name[:8]), encoding="utf8")
    (tmp_path / "zaken" / "zk-00001-mest" / "audit.log").write_text(
        "2026-05-12 14:30 [jev] zaak aangemaakt\n2026-07-12 13:17 [jev] index bewerkt\n",
        encoding="utf8",
    )
    return tmp_path


def _stamp_of(root: Path, store: str, name: str) -> str:
    fm, _ = schema.parse((root / store / name / "index.md").read_text("utf8"))
    return fm.get("gewijzigd", "")


def test_the_last_line_of_the_trail_becomes_the_change_stamp(layout9: Path) -> None:
    """The trail already knows when the zaak last changed; the stamp repeats it."""
    migrate_stamp_gewijzigd.main(layout9, apply=True)

    assert _stamp_of(layout9, "zaken", "zk-00001-mest") == "2026-07-12T13:17:00"
    text = (layout9 / "zaken" / "zk-00001-mest" / "index.md").read_text("utf8")
    keys = [m.group(1) for m in re.finditer(r"^(\w+):", text, re.MULTILINE)]
    assert keys[3:5] == ["aangemaakt", "gewijzigd"]  # where the next save puts it anyway


def test_a_zaak_without_a_trail_takes_its_date_of_intake(layout9: Path) -> None:
    migrate_stamp_gewijzigd.main(layout9, apply=True)
    assert _stamp_of(layout9, "prullenbak", "zk-00002-sloot") == "2026-05-12T14:30:00"


def test_the_stamp_migration_writes_nothing_on_a_dry_run(layout9: Path) -> None:
    before = _snapshot(layout9)
    assert migrate_stamp_gewijzigd.main(layout9, apply=False) > 0
    assert _snapshot(layout9) == before


def test_the_stamp_migration_stamps_the_layout_revision_and_is_idempotent(layout9: Path) -> None:
    migrate_stamp_gewijzigd.main(layout9, apply=True)
    after = _snapshot(layout9)

    assert migrate_stamp_gewijzigd.main(layout9, apply=True) == 0
    assert _snapshot(layout9) == after
    assert "version: 10" in (layout9 / ".app" / "config.yaml").read_text("utf8")


# ── The app migrates the data dir it is pointed at ────────────────────────────


def _point_at(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from odas.appconfig import get_config

    monkeypatch.setenv("ODAS_DATA_DIR", str(root))
    get_config.cache_clear()


def test_starting_against_an_old_data_dir_migrates_it(
    layout8: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deploy is one command: the app finds layout 8 and serves layout 9."""
    _point_at(layout8, monkeypatch)
    dataversion.ensure()

    assert dataversion.read_version() == dataversion.DATA_VERSION
    assert list((layout8 / ".backups").iterdir())  # it backed up before it wrote


def test_a_migration_at_start_is_written_to_the_log(
    layout8: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator reads app.log and sees the layouts the start went through, and the backup."""
    from odas.logging import setup_logging

    _point_at(layout8, monkeypatch)
    setup_logging("app")
    dataversion.ensure()

    text = (layout8 / ".app" / "logs" / "app.log").read_text("utf8")
    backup = next((layout8 / ".backups").iterdir())
    assert f"Data dir migrated: layout 8 -> {dataversion.DATA_VERSION}" in text
    assert f"backup={str(backup)!r}" in text


def test_a_failed_migration_at_start_is_written_to_the_log(
    layout8: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The container stops; the log still says which step broke, and where to revert from."""
    from odas.logging import setup_logging

    def broken(data_dir: Path, apply: bool) -> None:
        raise ValueError("unreadable index.md")

    _point_at(layout8, monkeypatch)
    setup_logging("app")
    monkeypatch.setitem(migrations.STEPS, 8, broken)
    with pytest.raises(SystemExit):
        dataversion.ensure()

    text = (layout8 / ".app" / "logs" / "app.log").read_text("utf8")
    assert "Migration failed: layout 8 -> " in text
    assert "unreadable index.md" in text  # the stack trace, under the line
    assert f"revert from {str(layout8 / '.backups')!r}" in text


def test_a_data_dir_that_is_already_current_is_left_alone(
    layout8: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second start writes nothing, and makes no second backup."""
    _point_at(layout8, monkeypatch)
    dataversion.ensure()
    after = _snapshot(layout8)

    dataversion.ensure()
    assert _snapshot(layout8) == after


def test_a_data_dir_from_a_newer_app_still_refuses_to_run(
    layout8: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migrating down is not a thing: the app that wrote it is the one to run it."""
    config = layout8 / ".app" / "config.yaml"
    config.write_text(config.read_text("utf8").replace("version: 8", "version: 99"), "utf8")
    _point_at(layout8, monkeypatch)

    with pytest.raises(SystemExit, match="Upgrade the app"):
        dataversion.ensure()


# ── Layout 10 → 11: the organisation names its overview columns ──────────────


LAYOUT10_CONFIG = """version: 10               # on-disk layout revision

org:
  display_name: Stichting Veenwacht
  app_title: Hulpvraag

types:
  hulpvraag:
    status:
      type: status          # the four generic values come with the type
      public: true
    zwaarte:
      type: [afwijzing, eenvoudig]
    behandelaar:
      type: user
    contact_naam:
      type: str
      label: Contactpersoon naam
      column: true          # this team scans the list by who asked
    termijn:
      type: termijn
      public: true
"""


@pytest.fixture
def layout10(tmp_path: Path) -> Path:
    """A layout-10 data dir: the columns are marked field by field."""
    (tmp_path / ".app").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".app" / "config.yaml").write_text(LAYOUT10_CONFIG, encoding="utf8")
    return tmp_path


def _config_text(root: Path) -> str:
    return (root / ".app" / "config.yaml").read_text("utf8")


def test_the_columns_the_data_dir_showed_become_one_list_under_org(layout10: Path) -> None:
    """The table keeps the columns it had, in the order it had them."""
    migrate_columns_to_org.main(layout10, apply=True)

    assert "  columns: [aangemaakt, status, behandelaar, contact_naam, termijn]" in _config_text(
        layout10
    )


def test_the_column_flag_is_gone_from_every_field(layout10: Path) -> None:
    """The key no longer exists, so a leftover would stop the app at start."""
    migrate_columns_to_org.main(layout10, apply=True)
    text = _config_text(layout10)

    assert "column:" not in text.replace("columns:", "")
    assert "label: Contactpersoon naam" in text  # the field itself stays


def test_a_data_dir_without_an_org_section_gets_one(tmp_path: Path) -> None:
    """A config that declares no branding still needs somewhere to name its columns."""
    (tmp_path / ".app").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".app" / "config.yaml").write_text(
        "version: 10\n\ntypes:\n  procedure:\n    status:\n      type: status\n", encoding="utf8"
    )
    migrate_columns_to_org.main(tmp_path, apply=True)

    assert "org:\n  columns: [aangemaakt, status]\n" in _config_text(tmp_path)


def test_the_column_migration_writes_nothing_on_a_dry_run(layout10: Path) -> None:
    before = _snapshot(layout10)
    assert migrate_columns_to_org.main(layout10, apply=False) > 0
    assert _snapshot(layout10) == before


def test_the_column_migration_stamps_the_layout_revision_and_is_idempotent(
    layout10: Path,
) -> None:
    migrate_columns_to_org.main(layout10, apply=True)
    after = _snapshot(layout10)

    assert migrate_columns_to_org.main(layout10, apply=True) == 0
    assert _snapshot(layout10) == after
    assert "version: 11" in _config_text(layout10)


# ── Layout 11 → 12: a mail entry carries the time it was sent ────────────────

MAIL_ENTRY = """---
onderwerp: Besluit # korte titel, bv. zienswijze
van: gemeente@venlo.example.nl # systeem: afzender
---

Zie bijlage.
"""


def _eml(date_header: str, forwards: str = "") -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Besluit"
    msg["Date"] = date_header
    msg.set_content("Zie bijlage.")
    if forwards:
        letter = EmailMessage()
        letter["Date"] = forwards
        letter.set_content("Het ontwerp.")
        msg.add_attachment(letter)
    return msg.as_bytes()


@pytest.fixture
def layout11(tmp_path: Path) -> Path:
    """A layout-11 tree: a received mail, a forward, a typed note; none has a time."""
    (tmp_path / ".app").mkdir(exist_ok=True)
    (tmp_path / ".app" / "config.yaml").write_text(
        "version: 11              # on-disk layout revision\ntypes: {}\n", encoding="utf8"
    )
    log = tmp_path / "zaken" / "zk-00001-mest" / "log"
    for name, raw in (
        ("2026-09-29-A-IN-besluit", _eml("Tue, 29 Sep 2026 12:00:00 +0000")),
        (
            "2026-09-29-B-IN-besluit",
            _eml("Tue, 29 Sep 2026 15:40:00 +0200", forwards="Tue, 29 Sep 2026 09:05:00 +0200"),
        ),
    ):
        (log / name).mkdir(parents=True)
        (log / name / "index.md").write_text(MAIL_ENTRY, encoding="utf8")
        (log / name / "bericht.eml").write_bytes(raw)
    (log / "2026-09-29-C-LOG-notitie.md").write_text(MAIL_ENTRY, encoding="utf8")
    return tmp_path


def _log_fm(root: Path, name: str) -> dict[str, str]:
    log = root / "zaken" / "zk-00001-mest" / "log"
    index = log / name / "index.md" if (log / name).is_dir() else log / f"{name}.md"
    return schema.parse(index.read_text("utf8"))[0]


def test_an_old_mail_entry_takes_its_time_from_the_message(layout11: Path) -> None:
    migrate_stamp_log_times.main(layout11, apply=True)

    assert _log_fm(layout11, "2026-09-29-A-IN-besluit")["aangemaakt"] == "2026-09-29T12:00:00+00:00"


def test_an_old_forward_takes_the_time_of_the_letter_it_carries(layout11: Path) -> None:
    migrate_stamp_log_times.main(layout11, apply=True)

    assert _log_fm(layout11, "2026-09-29-B-IN-besluit")["aangemaakt"] == "2026-09-29T07:05:00+00:00"


def test_an_old_typed_note_gets_no_time_it_never_had(layout11: Path) -> None:
    migrate_stamp_log_times.main(layout11, apply=True)

    assert "aangemaakt" not in _log_fm(layout11, "2026-09-29-C-LOG-notitie")


def test_the_log_time_migration_writes_nothing_on_a_dry_run(layout11: Path) -> None:
    before = _snapshot(layout11)
    assert migrate_stamp_log_times.main(layout11, apply=False) > 0
    assert _snapshot(layout11) == before


def test_the_log_time_migration_stamps_the_layout_revision_and_is_idempotent(
    layout11: Path,
) -> None:
    migrate_stamp_log_times.main(layout11, apply=True)
    after = _snapshot(layout11)

    assert migrate_stamp_log_times.main(layout11, apply=True) == 0
    assert _snapshot(layout11) == after
    assert "version: 12" in (layout11 / ".app" / "config.yaml").read_text("utf8")


def test_the_log_time_migration_keeps_every_other_byte_of_the_entry(layout11: Path) -> None:
    """A message body keeps its CRLF line ends; the stamp is the one line that changes."""
    index = layout11 / "zaken" / "zk-00001-mest" / "log" / "2026-09-29-A-IN-besluit" / "index.md"
    before = index.read_bytes().replace(b"Zie bijlage.\n", b"Zie\r\nbijlage.\r\n")
    index.write_bytes(before)

    migrate_stamp_log_times.main(layout11, apply=True)

    stamp = b'aangemaakt: "2026-09-29T12:00:00+00:00" # ISO tijdstip, niet wijzigen\n'
    assert index.read_bytes() == b"---\n" + stamp + before[4:]


FLAG_ZAAK = """---
id: {ref}
titel: Mest
aangemaakt: "2026-05-12T14:30:00"
gewijzigd: "2026-07-12T13:17:00"
---

Bewoners maken zich zorgen.
"""


@pytest.fixture
def layout12(tmp_path: Path) -> Path:
    """A layout-12 tree: a message last, a note last on the same day, no logboek."""
    (tmp_path / ".app").mkdir(exist_ok=True)
    (tmp_path / ".app" / "config.yaml").write_text(
        "version: 12              # on-disk layout revision\ntypes: {}\n", encoding="utf8"
    )
    for name, entries in (
        ("zk-00001-mest", ["2026-06-01-A-LOG-notitie.md", "2026-06-07-A-IN-vraag"]),
        ("zk-00002-sloot", ["2026-06-07-A-IN-vraag.md", "2026-06-07-B-LOG-gelezen.md"]),
        ("zk-00003-leeg", []),
    ):
        folder = tmp_path / "zaken" / name
        (folder / "log").mkdir(parents=True)
        (folder / "index.md").write_text(FLAG_ZAAK.format(ref=name[:8]), encoding="utf8")
        for entry in entries:
            index = (
                folder / "log" / entry
                if entry.endswith(".md")
                else folder / "log" / entry / "index.md"
            )
            index.parent.mkdir(exist_ok=True)
            index.write_text("---\nonderwerp: x\n---\n\nX.\n", encoding="utf8")
    return tmp_path


def _flag_of(root: Path, name: str) -> str:
    fm, _ = schema.parse((root / "zaken" / name / "index.md").read_text("utf8"))
    return fm.get("opvolgen", "")


def test_a_zaak_whose_last_entry_came_in_is_flagged_by_the_upgrade(layout12: Path) -> None:
    """No envelope the old rule showed is lost on the deploy."""
    migrate_flag_unanswered.main(layout12, apply=True)

    assert _flag_of(layout12, "zk-00001-mest") == "ja"


def test_a_zaak_whose_last_entry_is_a_note_is_not_flagged(layout12: Path) -> None:
    migrate_flag_unanswered.main(layout12, apply=True)

    assert _flag_of(layout12, "zk-00002-sloot") == ""  # the letter orders one day
    assert _flag_of(layout12, "zk-00003-leeg") == ""


def test_the_flag_migration_writes_nothing_on_a_dry_run(layout12: Path) -> None:
    before = _snapshot(layout12)
    assert migrate_flag_unanswered.main(layout12, apply=False) > 0
    assert _snapshot(layout12) == before


def test_the_flag_migration_stamps_the_layout_revision_and_is_idempotent(layout12: Path) -> None:
    migrate_flag_unanswered.main(layout12, apply=True)
    after = _snapshot(layout12)

    assert migrate_flag_unanswered.main(layout12, apply=True) == 0
    assert _snapshot(layout12) == after
    assert "version: 13" in (layout12 / ".app" / "config.yaml").read_text("utf8")
