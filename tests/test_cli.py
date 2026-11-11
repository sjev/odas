"""The CLI: the data/app compatibility gate, and `odas check` over a data dir."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import write_config
from typer.testing import CliRunner

from odas import dataversion, migrations
from odas.cli import app


def _write_version(tmp_path: Path, version: object) -> None:
    """A config carrying an explicit layout revision, valid in every other way."""
    from conftest import LOG_FIELDS

    config: dict[str, object] = {"types": {"hulpvraag": {}}, "fields": LOG_FIELDS}
    if version is not None:
        config["version"] = version
    write_config(tmp_path, config if version is not None else {**config, "version": None})


def test_a_data_dir_of_this_layout_is_accepted(tmp_path: Path) -> None:
    _write_version(tmp_path, dataversion.DATA_VERSION)

    dataversion.ensure()  # no exception is the assertion

    assert dataversion.read_version() == dataversion.DATA_VERSION


def test_an_older_layout_is_migrated(tmp_path: Path) -> None:
    """A deploy that bumps the layout needs no second command."""
    _write_version(tmp_path, dataversion.DATA_VERSION - 1)

    dataversion.ensure()

    assert dataversion.read_version() == dataversion.DATA_VERSION


def test_a_layout_below_the_oldest_step_is_refused(tmp_path: Path) -> None:
    """Nothing here lifts a data dir that old; the hand steps are written down."""
    _write_version(tmp_path, migrations.OLDEST - 1)

    with pytest.raises(SystemExit, match="too old"):
        dataversion.ensure()


def test_a_newer_layout_is_refused(tmp_path: Path) -> None:
    """An older app must not write into a data dir a newer one migrated."""
    _write_version(tmp_path, dataversion.DATA_VERSION + 1)

    with pytest.raises(SystemExit, match="newer"):
        dataversion.ensure()


def test_a_config_without_a_version_is_refused(tmp_path: Path) -> None:
    _write_version(tmp_path, None)

    with pytest.raises(SystemExit, match="declares no `version:`"):
        dataversion.ensure()


def test_an_unparsable_version_is_refused(tmp_path: Path) -> None:
    _write_version(tmp_path, "rommel")

    with pytest.raises(SystemExit, match="declares no `version:`"):
        dataversion.ensure()


def test_check_refuses_incompatible_data(tmp_path: Path) -> None:
    _write_version(tmp_path, dataversion.DATA_VERSION + 1)

    result = CliRunner().invoke(app, ["check"])

    assert result.exit_code != 0


def test_check_passes_on_the_example_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`odas check` is the promise to a jurist that their folder is still readable."""
    from conftest import use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    result = CliRunner().invoke(app, ["check"])

    assert result.exit_code == 0, result.output
    assert "valid" in result.output


def test_check_reports_a_broken_zaak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from conftest import ZAAK_FOLDER, use_example_data

    data = use_example_data("veenwacht", tmp_path, monkeypatch)
    (data / "zaken" / ZAAK_FOLDER / "index.md").write_text("---\nsoort: [\n---\n", encoding="utf8")

    result = CliRunner().invoke(app, ["check"])

    assert result.exit_code != 0
    assert ZAAK_FOLDER in result.output


def test_the_mail_daemon_writes_its_records_to_the_mail_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The daemon is a container of its own, so its records stand in a file of their own."""
    import logging

    from odas import mailin_server

    _write_version(tmp_path, dataversion.DATA_VERSION)
    monkeypatch.setattr(
        mailin_server, "run", lambda: logging.getLogger("odas.mailin").info("filed a message")
    )

    result = CliRunner().invoke(app, ["mailin"])

    assert result.exit_code == 0, result.output
    logs = tmp_path / ".app" / "logs"
    assert "filed a message" in (logs / "mail.log").read_text(encoding="utf8")
    assert not (logs / "app.log").exists()  # the web server writes that one, and it never ran


def _show(*args: str) -> str:
    """What `odas show` printed. The exit code is not the payload; the text is."""
    result = CliRunner().invoke(app, ["show", *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_a_shown_zaak_carries_its_state_and_the_body_of_every_log_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One command puts the whole case in front of a reader: what it is, and what happened."""
    from conftest import ZAAK, ZAAK_TITEL, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    out = _show(ZAAK)

    assert f"titel: {ZAAK_TITEL}" in out
    assert "status: in_behandeling" in out
    assert "log/2026-05-01-A-LOG-beoordeling-ecologisch-onderzoek" in out
    # the body of that entry, read back from the file the entry keeps it in
    assert "De AERIUS-berekening gaat uit van de vergunde situatie" in out


def test_the_log_entries_appear_in_the_order_their_names_carry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The name carries the order, so a restored copy reads like the original."""
    import os
    import time

    from conftest import ZAAK, ZAAK_FOLDER, use_example_data

    data = use_example_data("veenwacht", tmp_path, monkeypatch)
    # Touch the oldest entry so its mtime is the newest of all: order must not move.
    oldest = (
        data / "zaken" / ZAAK_FOLDER / "log" / "2026-01-06-A-LOG-vooraankondiging-ontwerpbesluit.md"
    )
    os.utime(oldest, (time.time() + 60, time.time() + 60))

    out = _show(ZAAK)

    names = [line for line in out.splitlines() if line.startswith("log/")]
    assert names == sorted(names)
    assert names[0] == "log/2026-01-06-A-LOG-vooraankondiging-ontwerpbesluit"


def test_a_limit_keeps_the_newest_entries_and_drops_the_older_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A case with two dozen letters still fits a reader who wants the recent ones."""
    from conftest import ZAAK, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    out = _show(ZAAK, "--limit", "2")

    names = [line for line in out.splitlines() if line.startswith("log/")]
    assert names == [
        "log/2026-06-09-A-IN-reactie-vereniging-via-inzienpagina",
        "log/2026-06-23-A-IN-ontvangstbevestiging-bezwaarschrift",
    ]


def test_an_entry_heading_reads_its_name_back_as_a_date_a_position_and_a_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reader sees which letter of that day this is without counting letters."""
    from conftest import ZAAK, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    out = _show(ZAAK)

    # the third of the five entries filed on 6 June 2026
    assert "## 2026-06-06 \u00b7 3/5 \u00b7 LOG \u00b7 adviesvraag aan expert" in out
    assert "log/2026-06-06-C-LOG-adviesvraag-aan-expert" in out  # the exact name stays


def test_the_position_of_an_entry_counts_the_whole_day_under_a_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A limit shortens the reading, never the day an entry belongs to."""
    from conftest import ZAAK, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    out = _show(ZAAK, "--limit", "4")

    headings = [line for line in out.splitlines() if line.startswith("## 2026-06-07")]
    assert headings == [
        "## 2026-06-07 \u00b7 5/6 \u00b7 LOG \u00b7 interne beoordeling geuronderzoek",
        "## 2026-06-07 \u00b7 6/6 \u00b7 UIT \u00b7 concept bezwaarschrift ter controle",
    ]


def test_a_short_listing_names_every_entry_and_prints_no_bodies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reader who wants the timeline gets the names, not two dozen letters."""
    from conftest import ZAAK, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    full = _show(ZAAK)
    short = _show(ZAAK, "--short")

    names = [line for line in short.splitlines() if line.startswith("log/")]
    assert names == [line for line in full.splitlines() if line.startswith("log/")]
    # the body of an entry, which the full reading carries and this one does not
    assert "De AERIUS-berekening gaat uit van de vergunde situatie" in full
    assert "De AERIUS-berekening gaat uit van de vergunde situatie" not in short


def test_a_short_listing_still_names_the_documents_of_an_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dropping the letters must not hide which documents a case holds."""
    from conftest import ZAAK, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    out = _show(ZAAK, "--short")

    documenten = out.split("log/2026-02-10-A-IN-hulpvraag")[1].split("documenten:")[1]
    assert "ontwerpbesluit-mestverwerking.pdf (tekst: nee, samenvatting: nee)" in documenten


def test_files_prints_the_path_of_every_document_of_a_zaak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conftest import ZAAK, ZAAK_FOLDER, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    result = CliRunner().invoke(app, ["files", ZAAK])

    assert result.exit_code == 0, result.output
    paths = [Path(line) for line in result.output.splitlines()]
    assert {p.name for p in paths} == {
        "definitief-besluit.pdf",
        "ontwerpbesluit-mestverwerking.pdf",
        "ecologisch-onderzoek.pdf",
    }
    assert all(p.is_file() and ZAAK_FOLDER in p.parts for p in paths)


def test_files_of_a_dossier_include_the_documents_of_its_zaken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conftest import ZAAK_FOLDER, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    result = CliRunner().invoke(app, ["files", "ds-4886"])

    assert result.exit_code == 0, result.output
    assert any(ZAAK_FOLDER in line for line in result.output.splitlines())


def test_a_direction_keeps_only_the_entries_that_carry_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What this case sent out is one question; what came in is another."""
    from conftest import ZAAK, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    out = _show(ZAAK, "--direction", "UIT")

    names = [line for line in out.splitlines() if line.startswith("log/")]
    assert names == ["log/2026-06-07-F-UIT-concept-bezwaarschrift-ter-controle"]


def test_a_direction_and_a_limit_together_give_the_newest_incoming_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The letter to answer is the last one that came in, whatever was sent after it."""
    from conftest import ZAAK, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    out = _show(ZAAK, "--direction", "IN", "--limit", "1")

    names = [line for line in out.splitlines() if line.startswith("log/")]
    assert names == ["log/2026-06-23-A-IN-ontvangstbevestiging-bezwaarschrift"]


def test_a_rule_of_dashes_opens_every_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two notes filed on one day stay two blocks, whatever headings their bodies carry."""
    from conftest import ZAAK, use_example_data

    from odas import cli_zaak

    use_example_data("veenwacht", tmp_path, monkeypatch)

    out = _show(ZAAK)

    blocks = out.split(cli_zaak.RULE + "\n")
    assert blocks[4].startswith("## 2026-05-01 \u00b7 1/2 \u00b7 LOG \u00b7 beoordeling")
    assert blocks[5].startswith("## 2026-05-01 \u00b7 2/2 \u00b7 LOG \u00b7 notitie")


def test_a_document_nobody_has_read_is_named_but_not_described(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silence about a document is an answer; a guess from its filename is not."""
    from conftest import ZAAK, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    out = _show(ZAAK)

    documenten = out.split("log/2026-02-10-A-IN-hulpvraag")[1].split("documenten:")[1]
    assert "ontwerpbesluit-mestverwerking.pdf (tekst: nee, samenvatting: nee)" in documenten


def test_a_sidecar_that_names_other_bytes_is_reported_as_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The text beside a document that was replaced describes the document that went."""
    from conftest import ZAAK, ZAAK_FOLDER, use_example_data

    from odas import index

    data = use_example_data("veenwacht", tmp_path, monkeypatch)
    doc = (
        data
        / "zaken"
        / ZAAK_FOLDER
        / "log"
        / "2026-02-10-A-IN-hulpvraag"
        / "ontwerpbesluit-mestverwerking.pdf"
    )
    index.write_text(doc, "hash-of-bytes-that-are-gone", ["een oude bladzijde"])

    out = _show(ZAAK)

    assert "ontwerpbesluit-mestverwerking.pdf (tekst: verouderd" in out
    assert "een oude bladzijde" not in out  # named as stale, never read from


def test_neither_the_reply_token_nor_the_toegang_list_reaches_the_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both are capabilities: the token opens a page, and the list names people."""
    from conftest import ZAAK, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    state = _show(ZAAK).split("\nlog/")[0]  # what the zaak itself declares

    assert "reply_token" not in state and "AO4UxhJdGxODffaYzTnJkQ" not in state
    assert "toegang" not in state and "f.wielinga@example.org" not in state
    # A caseworker who names a colleague in a note is the case record, not a field:
    # the entry bodies are printed as they stand.
    assert "f.wielinga@example.org" in _show(ZAAK)


def test_the_listing_reads_the_status_field_whatever_it_is_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Status is a kind, not a key: a data dir may name the field in its own words."""
    from conftest import ZAAK, rename_field, use_example_data

    from odas import index_write, zaak

    use_example_data("veenwacht", tmp_path, monkeypatch)
    rename_field(tmp_path, "hulpvraag", "status", "voortgang")
    folder = zaak.find(ZAAK)
    assert folder is not None
    index_write.set_field(folder, "voortgang", "wacht", by="jev")

    result = CliRunner().invoke(app, ["list"])

    assert result.exit_code == 0, result.output
    row = next(r for r in result.output.splitlines() if r.startswith(ZAAK))
    assert "wacht" in row


def test_the_listing_names_every_zaak_with_its_status_and_its_termijn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first thing a reader wants is which cases there are and what is due."""
    from conftest import ZAAK, ZAAK_TITEL, use_example_data

    from odas import zaak

    data = use_example_data("veenwacht", tmp_path, monkeypatch)

    result = CliRunner().invoke(app, ["list"])

    assert result.exit_code == 0, result.output
    # Any ref prefix, and any width: a migrated dossier still carries a four-digit ref.
    rows = [line for line in result.output.splitlines() if re.match(r"[a-z]{2}-\d+ ", line)]
    assert len(rows) == len(list((data / "zaken").iterdir()))
    row = next(r for r in rows if r.startswith(ZAAK))
    assert "in_behandeling" in row and "2026-06-26" in row and ZAAK_TITEL in row
    assert zaak.load(zaak.find(ZAAK) or data).token not in result.output


def test_agent_init_gives_the_data_dir_its_instructions_and_its_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A volume teaches a reader its own layout: nothing is typed into a prompt by hand."""
    from conftest import use_example_data

    data = use_example_data("veenwacht", tmp_path, monkeypatch)

    result = CliRunner().invoke(app, ["agent", "init"])

    assert result.exit_code == 0, result.output
    assert "zaken/" in (data / "CLAUDE.md").read_text(encoding="utf8")
    skill = (data / ".claude" / "skills" / "summarize" / "SKILL.md").read_text(encoding="utf8")
    assert "name: summarize" in skill


def test_agent_init_refuses_to_overwrite_what_somebody_edited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A volume's own notes are not scratch: --force is the way to say otherwise."""
    from conftest import use_example_data

    data = use_example_data("veenwacht", tmp_path, monkeypatch)
    (data / "CLAUDE.md").write_text("eigen aantekeningen\n", encoding="utf8")

    result = CliRunner().invoke(app, ["agent", "init"])

    assert result.exit_code != 0
    assert (data / "CLAUDE.md").read_text(encoding="utf8") == "eigen aantekeningen\n"

    forced = CliRunner().invoke(app, ["agent", "init", "--force"])

    assert forced.exit_code == 0, forced.output
    assert "zaken/" in (data / "CLAUDE.md").read_text(encoding="utf8")


def test_info_says_where_it_is_and_what_it_is_pointed_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first question in a terminal is which folder this command reads."""
    from conftest import VEENWACHT_ZAKEN, use_example_data

    data = use_example_data("veenwacht", tmp_path, monkeypatch)

    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == 0, result.output
    from odas import __version__

    assert str(Path.cwd()) in result.output
    assert str(data) in result.output
    assert str(data / ".app" / "config.yaml") in result.output
    assert __version__ in result.output
    assert str(dataversion.DATA_VERSION) in result.output
    assert str(VEENWACHT_ZAKEN) in result.output


def test_info_reports_a_layout_mismatch_instead_of_refusing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale data dir is the moment a person needs this command most."""
    from conftest import use_example_data

    data = use_example_data("veenwacht", tmp_path, monkeypatch)
    config = data / ".app" / "config.yaml"
    config.write_text(
        config.read_text(encoding="utf8").replace(
            f"version: {dataversion.DATA_VERSION}", f"version: {dataversion.DATA_VERSION - 1}"
        ),
        encoding="utf8",
    )

    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == 0, result.output
    assert str(dataversion.DATA_VERSION - 1) in result.output
    assert "odas upgrade" in result.output  # the command, not a hunt


def test_a_test_message_goes_out_over_the_configured_transport(tmp_path: Path) -> None:
    """`odas mail` proves the relay from the server, without waiting for a zaak event."""
    from conftest import use_outbox

    outbox = use_outbox(tmp_path)

    result = CliRunner().invoke(app, ["mail", "jurist@example.nl"])

    assert result.exit_code == 0, result.output
    sent = next(outbox.glob("*.eml")).read_text(encoding="utf8")
    assert "To: jurist@example.nl" in sent
    assert "ODAS" in sent


def test_a_data_dir_without_a_transport_says_nothing_was_sent(tmp_path: Path) -> None:
    """An empty `smtp.host` is a silent transport, so the verb must not report success."""
    result = CliRunner().invoke(app, ["mail", "jurist@example.nl"])

    assert result.exit_code != 0
    assert "No transport" in result.output


# ── `odas clean-log`: take the quoted chain out of the entries already on disk ──

QUOTED_BODY = """De perceelnummers volgen hieronder.

Met vriendelijke groet,
M. Dekker

-----Oorspronkelijk bericht-----
Van: Verhoeven <a.verhoeven@provincie.example.nl>
Onderwerp: Antwoord op het verzoek

Mag ik vandaag van u vernemen?
"""


def _quoted_entry() -> str:
    """The entry as a writer would put it on disk: frontmatter dumped, never typed."""
    from odas import schema

    fields = schema.log_fields()
    fm = {"onderwerp": "RE: Antwoord op het verzoek", "van": "m.dekker@veenwacht.example.nl"}
    return schema.dump({k: v for k, v in fm.items() if k in fields}, QUOTED_BODY, fields)


def _quoted_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, original: bool) -> Path:
    """A zaak holding one mail entry that repeats the message it answers."""
    from conftest import LEEG, use_example_data

    from odas import log_write, zaak

    use_example_data("veenwacht", tmp_path, monkeypatch)
    folder = zaak.find(LEEG)
    assert folder is not None
    raw = _quoted_entry()
    files = [("bericht.eml", raw.encode())] if original else []
    log_write.create_log_entry(folder, "UIT", "2026-08-26", raw, attachments=files)
    return folder


def _clean(*args: str) -> str:
    result = CliRunner().invoke(app, ["clean-log", *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_clean_log_reports_what_it_would_remove_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The verb shows the damage before it does any, so a reader can judge it first."""
    from conftest import LEEG

    from odas import zaak

    folder = _quoted_case(tmp_path, monkeypatch, original=True)

    out = _clean(LEEG)

    assert f"{LEEG}  log/2026-08-26-A-UIT-re-antwoord-op-het-verzoek  (5 lines)" in out
    # the words themselves, at the line each one holds in index.md
    assert "     17 | -----Oorspronkelijk bericht-----" in out
    assert "     21 | Mag ik vandaag van u vernemen?" in out
    assert "De perceelnummers volgen hieronder." not in out  # what stays is not offered
    assert "5 lines to remove in 1 entry." in out
    assert "Mag ik vandaag van u vernemen?" in zaak.load(folder).log_entries[0].body


def test_clean_log_shortens_an_entry_when_asked_to_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With --write the entry keeps its own words and drops the message it quotes."""
    from conftest import LEEG

    from odas import zaak

    folder = _quoted_case(tmp_path, monkeypatch, original=True)

    _clean(LEEG, "--write")

    body = zaak.load(folder).log_entries[0].body
    assert "De perceelnummers volgen hieronder." in body
    assert "Mag ik vandaag van u vernemen?" not in body
    assert body.endswith("*[eerder bericht weggelaten]*")


def test_clean_log_leaves_an_entry_that_has_no_original_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A note typed by hand has no second copy, so its words are never cut."""
    from conftest import LEEG

    from odas import zaak

    folder = _quoted_case(tmp_path, monkeypatch, original=False)

    out = _clean(LEEG, "--write")

    assert "Mag ik vandaag van u vernemen?" in zaak.load(folder).log_entries[0].body
    assert "skipped, no bericht.eml" in out


def test_clean_log_shows_every_line_when_asked_for_the_full_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A short preview hides the tail, so --full is there for a reader who wants all of it."""
    from conftest import LEEG

    _quoted_case(tmp_path, monkeypatch, original=True)

    assert "more lines" not in _clean(LEEG, "--full")  # nothing is held back


def test_clean_log_without_a_zaak_walks_every_zaak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One command reports the whole data dir, so a backfill needs no list of refs."""
    from conftest import LEEG, ZAAK

    from odas import log_write, zaak

    _quoted_case(tmp_path, monkeypatch, original=True)
    other = zaak.find(ZAAK)
    assert other is not None
    raw = _quoted_entry()
    log_write.create_log_entry(
        other, "UIT", "2026-08-27", raw, attachments=[("bericht.eml", raw.encode())]
    )

    out = _clean()

    assert f"{LEEG}  log/2026-08-26-A-UIT-re-antwoord-op-het-verzoek" in out
    assert f"{ZAAK}  log/2026-08-27-A-UIT-re-antwoord-op-het-verzoek" in out
    assert "10 lines to remove in 2 entries." in out


def _serve(monkeypatch: pytest.MonkeyPatch, *args: str) -> dict[str, object]:
    """Run `odas serve` without a web server: report what the server was given."""
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    seen: dict[str, object] = {}

    def fake_main(port: int | None = None) -> None:
        import os

        seen["port"] = port
        seen["bypass"] = os.getenv("ODAS_TEST_MODE")

    from odas import server

    monkeypatch.setattr(server, "main", fake_main)
    result = CliRunner().invoke(app, ["serve", *args])
    assert result.exit_code == 0, result.output
    return seen


def test_serve_keeps_the_sign_in_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plain `odas serve` still asks the identity provider who you are."""
    assert _serve(monkeypatch)["bypass"] is None


def test_no_auth_starts_the_server_with_the_dev_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--no-auth` lets you reach a local server without the remote sign-in."""
    assert _serve(monkeypatch, "--no-auth")["bypass"] == "1"


def test_a_port_option_overrides_the_port_the_data_dir_declares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--port` runs a local server next to the ports other services hold."""
    assert _serve(monkeypatch, "--port", "8001")["port"] == 8001


def test_serve_without_a_port_option_uses_the_port_of_the_data_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No port on the command line leaves the config in control."""
    assert _serve(monkeypatch)["port"] is None
