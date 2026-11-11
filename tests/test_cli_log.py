"""`odas log add`: a log entry filed from a terminal, the way the web form files it."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from odas.cli import app


def test_an_entry_added_from_a_terminal_is_filed_and_named_in_the_audit_trail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A prepared note lands in the case as a LOG entry, and the trail says who put it there."""
    from conftest import ZAAK, ZAAK_FOLDER, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)
    raw = "---\nonderwerp: Voorbereiding hulpvraag\nmarkdown: ja\n---\n\n## Vragen\n\n1. Mag dit?\n"

    result = CliRunner().invoke(
        app, ["log", "add", ZAAK, "-", "--datum", "2026-10-06", "--by", "claude"], input=raw
    )

    assert result.exit_code == 0, result.output
    folder = tmp_path / "zaken" / ZAAK_FOLDER
    entry = result.output.strip()  # the name it was filed under, for a script to pick up
    assert entry.startswith("2026-10-06-") and entry.endswith("-LOG-voorbereiding-hulpvraag")
    shown = CliRunner().invoke(app, ["show", ZAAK]).output
    assert f"log/{entry}" in shown
    assert "1. Mag dit?" in shown
    trail = (folder / "audit.log").read_text(encoding="utf8")
    assert "[claude] log-item aangemaakt (LOG): Voorbereiding hulpvraag" in trail


def test_an_unknown_zaak_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo in the ref files nothing anywhere."""
    from conftest import use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)

    result = CliRunner().invoke(app, ["log", "add", "zk-99999", "-"], input="---\n---\nx\n")

    assert result.exit_code != 0
    assert "unknown zaak: zk-99999" in result.output


def test_an_unknown_direction_files_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The terminal is held to the same rules as the form: a bad direction is named, not filed."""
    from conftest import ZAAK, ZAAK_FOLDER, use_example_data

    use_example_data("veenwacht", tmp_path, monkeypatch)
    log_dir = tmp_path / "zaken" / ZAAK_FOLDER / "log"
    before = sorted(p.name for p in log_dir.iterdir())

    result = CliRunner().invoke(
        app, ["log", "add", ZAAK, "-", "--direction", "UITT"], input="---\nonderwerp: x\n---\nx\n"
    )

    assert result.exit_code != 0
    assert "UITT" in result.output
    assert sorted(p.name for p in log_dir.iterdir()) == before
