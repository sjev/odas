"""The flag on a zaak: what still needs the team.

A message that comes in sets it. Only a person clears it, with the tick box on
the zaak page. A note or a reply leaves it standing: the team decides when the work
is done, not the order of the logboek.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import LEEG, ZAAK, post_log, token_of, write_config
from fastapi.testclient import TestClient
from test_overzicht import MARK, row_of

from odas import zaak
from odas.config import Config

LATER = "2026-07-01"  # after every log entry in the example data


def flag_of(ref: str) -> str:
    folder = zaak.find(ref)
    assert folder is not None
    return zaak.load(folder).frontmatter.get("opvolgen", "")


def tick(client: TestClient, ref: str, on: bool) -> None:
    data = {"flag": "ja"} if on else {}  # an unticked box posts nothing
    client.post(f"/zaken/{ref}/flag", data=data, follow_redirects=False)


def test_a_flagged_zaak_is_marked_in_the_list(client: TestClient) -> None:
    """ZAAK's newest entry came in, so the upgrade left it flagged."""
    assert flag_of(ZAAK) == "ja"
    assert MARK in row_of(client.get("/zaken").text, ZAAK)


def test_a_zaak_without_the_flag_is_not_marked(client: TestClient) -> None:
    assert MARK not in row_of(client.get("/zaken").text, LEEG)


def test_unticking_the_box_clears_the_flag(client: TestClient) -> None:
    """No note is needed to say a message needs nothing."""
    tick(client, ZAAK, on=False)

    assert flag_of(ZAAK) == ""
    assert MARK not in row_of(client.get("/zaken").text, ZAAK)


def test_ticking_the_box_sets_the_flag_without_a_message(client: TestClient) -> None:
    tick(client, LEEG, on=True)

    assert flag_of(LEEG) == "ja"
    assert MARK in row_of(client.get("/zaken").text, LEEG)


def test_the_change_of_the_flag_is_in_the_audit(client: TestClient) -> None:
    tick(client, ZAAK, on=False)

    folder = zaak.find(ZAAK)
    assert folder is not None
    assert "Opvolgen gewijzigd: ja → —" in zaak.load(folder).history


def test_the_zaak_page_shows_the_box_ticked_when_flagged(client: TestClient) -> None:
    page = client.get(f"/zaken/{ZAAK}").text
    box = page.split('name="flag"')[1].split(">")[0]

    assert "checked" in box


def test_the_zaak_page_shows_the_box_unticked_without_the_flag(client: TestClient) -> None:
    page = client.get(f"/zaken/{LEEG}").text
    box = page.split('name="flag"')[1].split(">")[0]

    assert "checked" not in box  # the box is there to find, ready to tick


@pytest.mark.parametrize("direction", ["LOG", "UIT"])
def test_a_note_or_a_reply_leaves_the_flag_standing(client: TestClient, direction: str) -> None:
    """An internal discussion is no sign the work is done."""
    post_log(client, f"/zaken/{ZAAK}", onderwerp="overleg", direction=direction, entry_date=LATER)

    assert flag_of(ZAAK) == "ja"


def test_a_message_that_comes_in_sets_the_flag_again(client: TestClient) -> None:
    tick(client, ZAAK, on=False)
    post_log(client, f"/zaken/{ZAAK}", onderwerp="rappel", direction="IN", entry_date=LATER)

    assert flag_of(ZAAK) == "ja"


def test_a_reply_of_the_indiener_sets_the_flag(client: TestClient) -> None:
    client.post(
        f"/inzien-{token_of(LEEG)}",
        data={"naam": "Piet", "onderwerp": "Aanvulling", "bericht": "Nog een stuk."},
    )

    assert flag_of(LEEG) == "ja"


def test_the_indiener_does_not_see_the_flag(client: TestClient) -> None:
    page = client.get(f"/inzien-{token_of(ZAAK)}").text

    assert 'name="flag"' not in page
    assert "Opvolgen" not in page


def _start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, declared: bool) -> str:
    """Start the app on the shipped template, with or without its flag; return the log."""
    from odas.app import create_app
    from odas.configload import TEMPLATE

    config = yaml.safe_load(TEMPLATE.read_text(encoding="utf8"))
    if not declared:
        for fields in config["types"].values():
            fields.pop("opvolgen", None)
    write_config(tmp_path, config)
    create_app()
    return Config().log_file("app").read_text(encoding="utf8")


def test_the_log_warns_at_startup_when_no_type_declares_a_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the declaration an IN marks nothing; the operator reads why."""
    log = _start(tmp_path, monkeypatch, declared=False)

    assert "[WARNING]" in log and "No type declares a flag field" in log


def test_the_log_stays_quiet_when_a_type_declares_a_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "[WARNING]" not in _start(tmp_path, monkeypatch, declared=True)
