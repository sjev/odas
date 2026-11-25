"""A zaak as one text: index.md and the log, for a person to paste into an AI tool.

The text is the case as it stands on disk, file by file. An attachment is named,
never read in: the text is for a chat box, not for an archive.
"""

from __future__ import annotations

from conftest import DOSSIER, LEEG, ZAAK, ZAAK_FOLDER, token_of
from fastapi.testclient import TestClient

from odas import log_write, zaak


def test_the_text_holds_the_case_and_its_log_and_names_each_attachment(
    client: TestClient,
) -> None:
    folder = zaak.find(ZAAK)
    assert folder is not None

    r = client.get(f"/zaken/{ZAAK}/export.md")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert f'filename="{ZAAK_FOLDER}.md"' in r.headers["content-disposition"]
    text = r.text
    assert (folder / "index.md").read_text(encoding="utf8") in text
    entries = zaak.scan_log(folder)
    positions = [text.index(f"## log/{e.name}\n") for e in entries]
    assert positions == sorted(positions)  # the log reads in its own order
    for e in entries:
        raw = folder / "log" / e.name
        source = raw / "index.md" if raw.is_dir() else raw.with_name(f"{e.name}.md")
        assert source.read_text(encoding="utf8").strip() in text
    assert "ontwerpbesluit-mestverwerking.pdf" in text
    assert "%PDF" not in text


def test_the_text_leaves_out_the_token_the_audit_log_and_the_prullenbak(
    client: TestClient,
) -> None:
    """Like the zip, the text leaves the building."""
    folder = zaak.find(LEEG)
    assert folder is not None
    gone = log_write.create_log_entry(
        folder, "LOG", "2026-05-20", "---\nonderwerp: weg\n---\n\nWeggegooide notitie.\n"
    ).stem
    client.post(f"/zaken/{LEEG}/log/{gone}/verwijderen")

    text = client.get(f"/zaken/{LEEG}/export.md").text

    assert token_of(LEEG) not in text
    assert "Weggegooide notitie" not in text
    assert (folder / "audit.log").read_text(encoding="utf8").strip() not in text


def test_the_text_of_a_dossier_leaves_its_zaken_out(client: TestClient) -> None:
    folder = zaak.find(ZAAK)
    assert folder is not None
    member_entry = zaak.scan_log(folder)[0].name

    text = client.get(f"/zaken/{DOSSIER}/export.md").text

    assert member_entry not in text


def test_the_zaak_page_offers_the_text_to_download_and_to_copy(client: TestClient) -> None:
    page = client.get(f"/zaken/{ZAAK}").text
    assert "Zaak als tekst" in page
    assert f'href="/zaken/{ZAAK}/export.md"' in page
    assert f'data-copy-url="/zaken/{ZAAK}/export.md"' in page


def test_the_inzien_page_offers_no_text_export(client: TestClient) -> None:
    page = client.get(f"/inzien-{token_of(ZAAK)}").text
    assert "export.md" not in page
