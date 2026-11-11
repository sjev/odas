"""The Markdown box on a log entry: plain text unless a person ticks it."""

from __future__ import annotations

from pathlib import Path

from conftest import LEEG, post_log
from fastapi.testclient import TestClient

from odas import log_write, zaak

BASE = f"/zaken/{LEEG}"  # an example zaak with no log yet


def _folder() -> Path:
    folder = zaak.find(LEEG)
    assert folder is not None
    return folder


def _shown(client: TestClient) -> str:
    """The block the zaak page draws the text of the first entry in."""
    return client.get(BASE).text.split('class="entry-text')[1].split("</div>")[0]


def test_an_entry_marked_markdown_is_shown_as_markdown(client: TestClient) -> None:
    """With the Markdown box ticked, a numbered line becomes a list and stars become emphasis."""
    body = "Punten:\n\n1. eerste\n2. tweede\n\n*let op*"
    assert post_log(client, BASE, onderwerp="notitie", body=body, markdown="ja").status_code == 303

    shown = _shown(client)
    assert "<li>eerste</li>" in shown
    assert "<em>let op</em>" in shown


def test_the_new_entry_form_offers_the_markdown_box_unticked(client: TestClient) -> None:
    """A new entry starts as plain text; the person ticks the box to change that."""
    form = client.get(BASE).text.split('id="log-form"')[1].split("</form>")[0]
    box = form.split('name="markdown"')[0].rsplit("<input", 1)[1] + 'name="markdown"'
    rest = form.split('name="markdown"')[1].split(">")[0]
    assert 'type="checkbox"' in box
    assert "checked" not in box + rest


def test_a_ticked_box_stands_in_the_entry_on_disk(client: TestClient) -> None:
    """The choice is a line in the file, so grep finds every Markdown entry."""
    post_log(client, BASE, onderwerp="notitie", body="tekst", markdown="ja")

    assert zaak.load(_folder()).log_entries[0].frontmatter["markdown"] == "ja"


def test_unticking_the_box_shows_the_entry_as_plain_text_again(client: TestClient) -> None:
    """The edit page shows the box ticked; saving it unticked turns the Markdown off."""
    name = log_write.create_log_entry(
        _folder(), "LOG", "2026-05-20", "---\nonderwerp: notitie\nmarkdown: ja\n---\n\n*let op*\n"
    ).stem
    assert "checked" in client.get(f"{BASE}/log/{name}/bewerken").text.split('name="markdown"')[1]

    r = client.post(
        f"{BASE}/log/{name}/bewerken", data={"body": "*let op*"}, follow_redirects=False
    )
    assert r.status_code == 303

    shown = _shown(client)
    assert "*let op*" in shown
    assert "<em>" not in shown


def test_markdown_in_an_entry_cannot_run_a_script(client: TestClient) -> None:
    """Raw HTML in a Markdown entry is removed, not run."""
    body = "Hallo <script>alert(1)</script>"
    post_log(client, BASE, onderwerp="notitie", body=body, markdown="ja")

    shown = _shown(client)
    assert "Hallo" in shown
    assert "<script" not in shown


def test_a_box_value_other_than_ja_is_refused(client: TestClient) -> None:
    """Only `ja` turns Markdown on, so any other value is an error and writes nothing."""
    post_log(client, BASE, onderwerp="notitie", body="tekst", markdown="nee")

    assert zaak.load(_folder()).log_entries == []


def test_a_link_in_a_markdown_entry_opens_in_a_new_tab(client: TestClient) -> None:
    """A reader who follows a source keeps the zaak page open behind it."""
    body = "Zie [art. 8:14 Awb](https://wetten.overheid.nl/jci1.3:c:BWBR0005537&artikel=8:14)."
    assert post_log(client, BASE, onderwerp="notitie", body=body, markdown="ja").status_code == 303

    link = _shown(client).split("<a ")[1].split(">")[0]
    assert 'href="https://wetten.overheid.nl/' in link
    assert 'target="_blank"' in link
    assert "noopener" in link  # the opened page gets no handle back on this one
