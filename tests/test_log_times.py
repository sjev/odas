"""The time of a log entry: when it happened, and whether it was changed since.

The name holds the day and the order. The frontmatter holds the moments:
`aangemaakt` and `gewijzigd`, as on the zaak itself.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import LEEG, TEAMLID, ZAAK, post_log, write_config
from fastapi.testclient import TestClient
from pydantic import ValidationError

from odas import clock, log_write, mailin_store, zaak, zaak_create
from odas.settings import OrgProfile

BASE = f"/zaken/{LEEG}"


def _folder() -> Path:
    folder = zaak.find(LEEG)
    assert folder is not None
    return folder


def _today() -> str:
    """Today by the clock of the example orgs, which name no timezone of their own."""
    return datetime.now(ZoneInfo("Europe/Amsterdam")).date().isoformat()


def _here(stamp: str) -> str:
    """A UTC stamp from disk as the page shows it: HH:MM on the clock of the org."""
    return f"{datetime.fromisoformat(stamp).astimezone(ZoneInfo('Europe/Amsterdam')):%H:%M}"


def stamps(html: str) -> list[str]:
    """The date and time above each entry, as a person reads them."""
    cells = re.findall(r'<div class="ts">(.*?)</div>', html, re.S)
    return [" ".join(re.findall(r'<span(?: class="time")?>([^<]*)<', cell)) for cell in cells]


def test_a_new_log_entry_shows_the_time_it_was_recorded(client: TestClient) -> None:
    """Two notes on one day read apart: each shows the time it was written."""
    today = _today()
    post_log(client, BASE, entry_date=today, onderwerp="notitie", body="Gebeld.")

    stamp = zaak.load(_folder()).log_entries[0].frontmatter["aangemaakt"]
    assert (
        datetime.fromisoformat(stamp).astimezone(ZoneInfo("Europe/Amsterdam")).date().isoformat()
        == today
    )
    assert stamps(client.get(BASE).text) == [f"{today.replace('-', '.')} {_here(stamp)}"]


def _mail(date_header: str, forwards: str = "") -> bytes:
    """A received message; `forwards` puts a letter with that date inside it."""
    msg = EmailMessage()
    msg["From"] = TEAMLID if forwards else "gemeente@venlo.example.nl"  # a colleague forwards
    msg["To"] = f"{LEEG}@odas.example.nl"
    msg["Subject"] = "Besluit"
    msg["Date"] = date_header
    msg.set_content("Zie bijlage.")
    if forwards:
        letter = EmailMessage()
        letter["From"] = "provincie@limburg.example.nl"
        letter["Subject"] = "Ontwerpbesluit"
        letter["Date"] = forwards
        letter.set_content("Het ontwerp.")
        msg.add_attachment(letter)
    return msg.as_bytes()


def test_a_received_mail_shows_the_time_it_was_sent_in_amsterdam(client: TestClient) -> None:
    """A message stamped in UTC reads in the clock of the org: summer time is two hours on."""
    mailin_store.file_message(_folder(), "IN", _mail("Tue, 29 Sep 2026 12:00:00 +0000"))

    assert stamps(client.get(BASE).text) == ["2026.09.29 14:00"]


def test_a_mail_sent_just_before_midnight_utc_is_filed_on_the_next_day_here(
    client: TestClient,
) -> None:
    """The day in the name and the time beside it come from the same clock."""
    mailin_store.file_message(_folder(), "IN", _mail("Mon, 28 Sep 2026 23:30:00 +0000"))

    (entry,) = zaak.load(_folder()).log_entries
    assert entry.datum == "2026-09-29"
    assert stamps(client.get(BASE).text) == ["2026.09.29 01:30"]


def test_a_data_dir_names_its_own_timezone(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An org elsewhere reads the same message by its own clock."""
    config = tmp_path / ".app" / "config.yaml"
    text = config.read_text("utf8").replace("org:\n", "org:\n  timezone: America/New_York\n", 1)
    write_config(tmp_path, text)
    mailin_store.file_message(_folder(), "IN", _mail("Tue, 29 Sep 2026 12:00:00 +0000"))

    assert stamps(client.get(BASE).text) == ["2026.09.29 08:00"]


def test_an_unknown_timezone_stops_the_app_at_start() -> None:
    with pytest.raises(ValidationError, match="Mars/Olympus"):
        OrgProfile(timezone="Mars/Olympus")


def test_a_forward_shows_the_time_of_the_letter_it_carries(client: TestClient) -> None:
    """The letter was sent in the morning; the forward came in the afternoon."""
    raw = _mail("Tue, 29 Sep 2026 15:40:00 +0200", forwards="Tue, 29 Sep 2026 09:05:00 +0200")
    mailin_store.file_message(_folder(), "IN", raw)

    assert stamps(client.get(BASE).text) == ["2026.09.29 09:05"]


def test_a_back_dated_entry_shows_its_date_and_no_time(client: TestClient) -> None:
    """Typed today about last year: a time from today would be false."""
    post_log(client, BASE, entry_date="2025-01-03", onderwerp="notitie", body="Achteraf.")

    assert zaak.load(_folder()).log_entries[0].frontmatter["aangemaakt"]  # still recorded
    assert stamps(client.get(BASE).text) == ["2025.01.03"]


def test_an_entry_a_person_changed_says_so_and_when(client: TestClient) -> None:
    """The time stays the time it was written; the marker gives the time of the change."""
    today = _today()
    post_log(client, BASE, entry_date=today, onderwerp="notitie", body="Eerst.")
    before = zaak.load(_folder()).log_entries[0]

    client.post(f"{BASE}/log/{before.name}/bewerken", data={"body": "Aangepast."})

    after = zaak.load(_folder()).log_entries[0]
    assert after.frontmatter["aangemaakt"] == before.frontmatter["aangemaakt"]
    changed = after.frontmatter["gewijzigd"]
    html = client.get(BASE).text
    assert f'title="gewijzigd op {today.replace("-", ".")} {_here(changed)}">bewerkt<' in html


def test_a_new_entry_is_not_marked_as_changed(client: TestClient) -> None:
    post_log(client, BASE, entry_date=_today(), onderwerp="notitie", body="x")

    assert ">bewerkt<" not in client.get(BASE).text


def test_a_line_the_app_adds_to_an_entry_is_no_change_by_a_person(client: TestClient) -> None:
    """The intake adds whether the confirmation went; nobody edited the entry."""
    name = log_write.write_log_entry(_folder(), "IN", "indiening", "Formulier.").stem
    raw = log_write.read_log_entry_raw(_folder(), name) or ""
    log_write.update_log_entry(_folder(), name, f"{raw}\nBevestiging verstuurd.\n")

    assert ">bewerkt<" not in client.get(BASE).text


def test_an_entry_from_before_the_stamps_shows_its_date_as_before(client: TestClient) -> None:
    """The example note was typed before entries carried a time."""
    html = client.get(f"/zaken/{ZAAK}").text

    assert "2026.01.06" in stamps(html)


# ── Stored in UTC, shown on the clock of the org ─────────────────────────────


def test_a_log_time_is_stored_in_utc_whatever_zone_the_message_used(client: TestClient) -> None:
    """The disk holds one clock; the page turns it into the clock of the org."""
    raw = _mail("Tue, 29 Sep 2026 15:40:00 +0200", forwards="Tue, 29 Sep 2026 09:05:00 +0200")
    mailin_store.file_message(_folder(), "IN", raw)

    (entry,) = zaak.load(_folder()).log_entries
    assert entry.frontmatter["aangemaakt"] == "2026-09-29T07:05:00+00:00"


def test_a_zaak_made_after_midnight_here_shows_the_day_here(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """00:30 in Amsterdam is still the day before in UTC; the page shows the day here."""
    moment = datetime(2026, 9, 28, 22, 30, tzinfo=UTC).astimezone(ZoneInfo("Europe/Amsterdam"))
    monkeypatch.setattr(clock, "now", lambda: moment)  # the seam: the clock of the org

    z = zaak_create.create_minimal("Nachtwerk", "hulpvraag")

    assert z.frontmatter["aangemaakt"] == "2026-09-28T22:30:00+00:00"
    assert z.frontmatter["gewijzigd"] == "2026-09-28T22:30:00+00:00"
    assert "aangemaakt 2026.09.29" in client.get(f"/zaken/{z.ref}").text


def test_a_stamp_without_a_zone_is_read_on_the_clock_of_the_org(client: TestClient) -> None:
    """The example data was stamped before stamps carried a zone; its dates stay as they were."""
    z = zaak.load(zaak.find(ZAAK) or _folder())

    assert z.created is not None
    assert z.created.utcoffset() == ZoneInfo("Europe/Amsterdam").utcoffset(z.created)
