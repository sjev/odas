"""A zaak as one text: its fields, summary and log, for a person to paste into an AI tool.

The reader is a model that knows nothing of ODAS. The text says what each part
is and drops what only the app needs. An attachment is named, never read in.
"""

from __future__ import annotations

from conftest import DOSSIER, LEEG, ZAAK, ZAAK_FOLDER, ZAAK_TITEL, token_of
from fastapi.testclient import TestClient

from odas import index, log_write, zaak


def test_the_text_opens_with_a_reading_key_then_gegevens_samenvatting_and_logboek(
    client: TestClient,
) -> None:
    """A model that never saw ODAS must tell the case from the log, and who sent what."""
    folder = zaak.find(ZAAK)
    assert folder is not None

    r = client.get(f"/zaken/{ZAAK}/export.md")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert f'filename="{ZAAK_FOLDER}.md"' in r.headers["content-disposition"]
    text = r.text
    assert text.startswith(f"# Zaak {ZAAK}: {ZAAK_TITEL}\n")
    assert "UIT = verstuurd door Stichting Veenwacht" in text
    sections = [text.index(h) for h in ("## 1. Gegevens", "## 2. Samenvatting", "## 3. Logboek")]
    assert sections == sorted(sections)
    assert "- Juridische procedure: De provincie wil" in text  # the label, not the disk key
    assert "### Samenvatting" in text  # the body's own heading sits below the export's
    entries = zaak.scan_log(folder)
    positions = [text.index(f"### {e.datum}") for e in entries]
    assert positions == sorted(positions)
    assert "### 2026-06-07 · UIT · concept bezwaarschrift ter controle" in text
    assert "Aan: m.janssen@example.com" in text


def test_the_text_drops_what_only_the_app_needs(client: TestClient) -> None:
    text = client.get(f"/zaken/{ZAAK}/export.md").text
    assert "niet wijzigen" not in text  # no YAML hints
    assert "Behandelaar" not in text  # empty on this zaak
    assert "51.162741" not in text  # coordinates
    assert "- Toegang:" not in text  # the access list; a note may still name a person
    assert "bcc" not in text.lower()


def test_an_attachment_is_named_and_its_content_is_left_out(client: TestClient) -> None:
    text = client.get(f"/zaken/{ZAAK}/export.md").text
    assert "Bijlage: ontwerpbesluit-mestverwerking.pdf" in text
    assert "%PDF" not in text
    assert "Samenvatting van de bijlage" not in text  # none was made


def test_an_attachment_brings_its_ai_summary_when_one_was_made(client: TestClient) -> None:
    folder = zaak.find(ZAAK)
    assert folder is not None
    pdf = folder / "log" / "2026-05-18-A-IN-definitief-besluit" / "definitief-besluit.pdf"
    index.write_summary(pdf, index.digest(pdf), "Het besluit staat de uitbreiding toe.", "test")

    text = client.get(f"/zaken/{ZAAK}/export.md").text

    after = text.split("Bijlage: definitief-besluit.pdf\n", 1)[1]
    assert after.startswith("Samenvatting van de bijlage:\nHet besluit staat de uitbreiding toe.")


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
