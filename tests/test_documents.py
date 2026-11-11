"""The documents of a zaak: what is inside them, on one screen.

Both the text of a document and what was made of it lie beside it, named after
it. The text is free to throw away and remake; a summary costs money every time,
so nothing rebuilds it. Where they live is the same answer for both, because a
person with `grep` and no app reads the whole case from the folder.
"""

from __future__ import annotations

import io
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from conftest import LEEG, TEAMLID, ZAAK, token_of
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from odas import cli, documents, index, log_write, schema, zaak

PDF = "log/2026-02-10-A-IN-hulpvraag/ecologisch-onderzoek.pdf"
ENTRY = "2026-02-10-A-IN-hulpvraag"
ONDERZOEK = "ecologisch-onderzoek.pdf"


def _folder(ref: str = ZAAK) -> Path:
    folder = zaak.find(ref)
    assert folder is not None
    return folder


def _clear_text(ref: str = ZAAK) -> None:
    """Throw away every extracted text of this zaak, the way a person with rm does."""
    for path in _folder(ref).rglob(f"*{zaak.TEXT_SUFFIX}"):
        path.unlink()


def _ai_url(name: str = ONDERZOEK, ref: str = ZAAK, entry: str = ENTRY) -> str:
    """Where a person asks for the summary of one document."""
    return f"/zaken/{ref}/log/{entry}/bijlage/{name}/samenvatting"


def _logboek(page: str) -> str:
    """The logboek of a zaak page, without the Documenten list that follows it."""
    return page.split('<h2 class="log-title">Documenten</h2>')[0]


def _wait_until_done(client: TestClient, ref: str = ZAAK, timeout: float = 10.0) -> None:
    """Let every running summary of this zaak finish, so no worker outlives the test."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if "bezig" not in client.get(f"/zaken/{ref}").text.lower():
            return
        time.sleep(0.02)
    raise AssertionError("a summary was still running when the test ended")


def post_log(client: TestClient, base: str, onderwerp: str, name: str, content: bytes) -> Any:
    """Add a log entry with one attached file, the way the inline form does."""
    return client.post(
        f"{base}/log",
        data={"direction": "IN", "entry_date": "2026-05-20", "onderwerp": onderwerp},
        files=[("documenten", (name, content, "application/octet-stream"))],
        follow_redirects=False,
    )


def _store_summary(ref: str, name: str, text: str) -> None:
    """Store a summary the way a person's agent does: through the command line."""
    result = CliRunner().invoke(cli.app, ["index", "summary", ref, name, "--set", "-"], input=text)
    assert result.exit_code == 0, result.output


def use_ai(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reply: str = "Onderzoek naar vleermuizen in het plangebied.",
) -> list[tuple[str, str]]:
    """Declare an `ai:` section and a key, and stand in for the provider.

    Returns the list of (document, prompt) pairs the model was handed, so a test
    can state what reached it without reaching into the client that sent it.
    """
    import yaml
    from conftest import write_config, write_secrets

    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["ai"] = {"model": "test/model", "prompt": "Schrijf 3 tot 5 Nederlandse zinnen."}
    write_config(tmp_path, config)
    write_secrets(tmp_path, {"ai_api_key": "sk-test"})

    seen: list[tuple[str, str]] = []

    def fake_ask(system: str, document: str, text: str) -> str:
        seen.append((document, f"{system}\n{text}"))
        return reply

    monkeypatch.setattr("odas.ai.ask", fake_ask)
    return seen


def _blank_pdf() -> bytes:
    """A PDF that is one empty page: a stand-in for a scan with no text layer."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_the_zaak_page_names_every_document_and_reads_back_its_summary(
    client: TestClient,
) -> None:
    """A jurist opens a zaak and sees each attachment, with the summary that was stored."""
    folder = _folder()
    documents.extract_folder(folder)
    _store_summary(ZAAK, "ecologisch-onderzoek.pdf", "Onderzoek naar vleermuizen.")

    page = client.get(f"/zaken/{ZAAK}").text

    assert "Documenten" in page
    for name in (
        "definitief-besluit.pdf",
        "ecologisch-onderzoek.pdf",
        "ontwerpbesluit-mestverwerking.pdf",
    ):
        assert name in page
    assert "Onderzoek naar vleermuizen." in page


def test_a_filed_pdf_is_extracted_without_any_command_being_run(client: TestClient) -> None:
    """A jurist adds a PDF to the log, and its text is beside it right away."""
    pdf = (_folder() / PDF).read_bytes()
    post_log(client, f"/zaken/{LEEG}", "Nieuw stuk", "a.pdf", pdf)

    beside = next(_folder(LEEG).rglob("a.pdf.tekst.md"))

    assert "Ecologisch onderzoek" in beside.read_text(encoding="utf8")


def test_the_text_of_a_document_lies_beside_it_in_the_zaak(client: TestClient) -> None:
    """A person opens the folder that holds a document and reads its words there."""
    folder = _folder()
    documents.extract_folder(folder)

    beside = folder / f"{PDF}.tekst.md"

    assert "Ecologisch onderzoek" in beside.read_text(encoding="utf8")


def test_grep_over_the_zaken_finds_a_word_that_is_only_inside_a_document(
    client: TestClient,
) -> None:
    """The one property: no app, no index, just the tree and what is written in it."""
    documents.extract_folder(_folder())
    zaken = _folder().parent

    hits = [p for p in zaken.rglob("*.tekst.md") if "Ecologisch onderzoek" in p.read_text("utf8")]

    assert [p.name for p in hits] == [f"{ONDERZOEK}.tekst.md"]


def test_the_extracted_text_keeps_the_page_boundary(client: TestClient) -> None:
    """The text of a document is stored page by page, so a snippet can name its page."""
    folder = _folder()
    documents.extract_folder(folder)

    text = index.text_of(folder / PDF, index.digest(folder / PDF)) or ""

    assert text.startswith("## p1")
    assert "Ecologisch onderzoek" in text


def test_the_same_document_in_two_zaken_carries_its_own_text_in_each(
    client: TestClient,
) -> None:
    """Each copy is a document of its own zaak, so each zaak folder is complete."""
    pdf = (_folder() / PDF).read_bytes()
    for ref in (LEEG, ZAAK):
        post_log(client, f"/zaken/{ref}", "Zelfde stuk", "kopie.pdf", pdf)

    beside = sorted(p.parents[2] for p in _folder().parent.rglob("kopie.pdf.tekst.md"))

    assert beside == sorted([_folder(LEEG), _folder(ZAAK)])


def test_a_document_without_a_text_layer_is_filed_and_its_row_warns(client: TestClient) -> None:
    """A scan is read, its text file is empty, and the row says it cannot be read."""
    scan = _blank_pdf()
    post_log(client, f"/zaken/{LEEG}", "Scan", "scan.pdf", scan)

    page = client.get(f"/zaken/{LEEG}").text
    beside = next(_folder(LEEG).rglob("scan.pdf.tekst.md"))

    assert "scan.pdf" in page
    assert "geen tekstlaag" in page
    assert index.text_of(beside.with_name("scan.pdf"), index.digest_of(scan)) == ""


def test_a_document_not_yet_indexed_shows_no_warning(client: TestClient) -> None:
    """A file dropped straight into the folder waits quietly for the sync command."""
    folder = _folder(LEEG)
    entry_dir = folder / "log" / "2026-05-20-A-IN-nieuw-stuk"
    entry_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(_folder() / PDF, entry_dir / "ecologisch-onderzoek.pdf")

    page = client.get(f"/zaken/{LEEG}").text

    assert "ecologisch-onderzoek.pdf" in page
    assert "geen tekstlaag" not in page


def test_throwing_away_all_the_text_keeps_every_summary(client: TestClient) -> None:
    """The text is derived and a summary is not, so clearing the text keeps it."""
    folder = _folder()
    documents.extract_folder(folder)
    _store_summary(ZAAK, "ecologisch-onderzoek.pdf", "Onderzoek naar vleermuizen.")

    _clear_text()

    assert "Onderzoek naar vleermuizen." in client.get(f"/zaken/{ZAAK}").text


def test_an_extraction_that_fails_still_files_the_log_entry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The document reader breaks, and the entry with its file is on disk regardless."""

    def boom(path: Path) -> list[str]:
        raise RuntimeError("stuk")

    monkeypatch.setattr(documents, "extract", boom)
    post_log(client, f"/zaken/{LEEG}", "Toch bewaard", "a.pdf", b"%PDF-1.4")

    entries = zaak.load(_folder(LEEG)).log_entries

    assert [Path(a).name for e in entries for a in e.attachments] == ["a.pdf"]


def test_a_document_that_is_not_a_pdf_is_a_row_without_a_warning(client: TestClient) -> None:
    """Every attachment is listed, and one the tool cannot read yet is no error."""
    post_log(client, f"/zaken/{LEEG}", "Foto", "foto.jpg", b"\xff\xd8\xff")

    page = client.get(f"/zaken/{LEEG}").text

    assert "foto.jpg" in page
    assert "geen tekstlaag" not in page


def test_the_zaak_page_answers_with_all_the_text_thrown_away(client: TestClient) -> None:
    """The folders stay the record: the text is derived and may simply be gone."""
    folder = _folder()
    documents.extract_folder(folder)
    _clear_text()

    page = client.get(f"/zaken/{ZAAK}")

    assert page.status_code == 200
    assert "definitief-besluit.pdf" in page.text


def test_a_document_under_its_logboek_item_says_how_many_pages_it_has(
    client: TestClient,
) -> None:
    """A jurist reads the logboek and sees the document itself, not only its name."""
    documents.extract_folder(_folder())

    logboek = _logboek(client.get(f"/zaken/{ZAAK}").text)

    assert ONDERZOEK in logboek
    assert "1 pagina" in logboek


def test_the_summary_of_a_document_is_readable_under_its_logboek_item(
    client: TestClient,
) -> None:
    """What was made of a document stands where the document was filed."""
    documents.extract_folder(_folder())
    _store_summary(ZAAK, ONDERZOEK, "Onderzoek naar vleermuizen.")

    logboek = _logboek(client.get(f"/zaken/{ZAAK}").text)

    assert "Onderzoek naar vleermuizen." in logboek


def test_the_indiener_does_not_see_the_documenten_section(client: TestClient) -> None:
    """The gathered list is the team's page; the indiener reads the logboek."""
    documents.extract_folder(_folder())

    page = client.get(f"/inzien-{token_of(ZAAK)}").text

    assert '<h2 class="log-title">Documenten</h2>' not in page


def test_the_indiener_reads_the_summary_under_the_logboek_item(client: TestClient) -> None:
    """The indiener sees the same row as the team: name, pages and summary."""
    documents.extract_folder(_folder())
    _store_summary(ZAAK, ONDERZOEK, "Onderzoek naar vleermuizen.")

    page = client.get(f"/inzien-{token_of(ZAAK)}").text

    assert "Onderzoek naar vleermuizen." in page


def test_the_cli_stores_a_summary_that_the_zaak_page_reads_back(client: TestClient) -> None:
    """A person's agent writes the summary through the command line, and the page shows it."""
    documents.extract_folder(_folder())
    _store_summary(ZAAK, "ecologisch-onderzoek.pdf", "Onderzoek naar vleermuizen.")

    assert "Onderzoek naar vleermuizen." in client.get(f"/zaken/{ZAAK}").text


def test_the_cli_prints_the_text_of_a_document_that_has_no_summary(client: TestClient) -> None:
    """The agent asks the zaak what still needs reading, and gets the text itself."""
    documents.extract_folder(_folder())

    result = CliRunner().invoke(cli.app, ["index", "text", ZAAK])

    assert result.exit_code == 0, result.output
    assert "ecologisch-onderzoek.pdf" in result.output
    assert "Ecologisch onderzoek" in result.output


def test_a_sync_backfills_a_folder_that_was_filled_by_hand(client: TestClient) -> None:
    """A document copied into the folder is picked up by the command, not by a visitor."""
    _clear_text()

    result = CliRunner().invoke(cli.app, ["index", "sync", ZAAK])

    assert result.exit_code == 0, result.output
    assert "3 documents, 3 pages, 0 warnings" in result.output
    assert "Ecologisch onderzoek" in (_folder() / f"{PDF}.tekst.md").read_text("utf8")


def test_a_sync_skips_a_document_that_is_already_indexed(client: TestClient) -> None:
    """A second sync does not read a document again; its text is already beside it."""
    folder = _folder()
    documents.extract_folder(folder)
    beside = folder / f"{PDF}.tekst.md"
    kept = beside.read_text(encoding="utf8")

    CliRunner().invoke(cli.app, ["index", "sync", ZAAK])

    assert beside.read_text(encoding="utf8") == kept  # not rewritten, so not read again


def test_sync_force_reindexes_a_document_that_is_already_indexed(client: TestClient) -> None:
    """`--force` reads every document again, even one that already carries its text."""
    folder = _folder()
    documents.extract_folder(folder)
    beside = folder / f"{PDF}.tekst.md"
    beside.write_text("stale", encoding="utf8")

    result = CliRunner().invoke(cli.app, ["index", "sync", ZAAK, "--force"])

    assert result.exit_code == 0, result.output
    assert "Ecologisch onderzoek" in beside.read_text(encoding="utf8")


def test_a_text_file_names_the_document_and_its_page_count(client: TestClient) -> None:
    """A text file says what it came from, how long it is, and which bytes it read."""
    folder = _folder()
    CliRunner().invoke(cli.app, ["index", "sync", ZAAK])

    fm, body = schema.parse((folder / f"{PDF}.tekst.md").read_text("utf8"))

    assert fm["document"] == "ecologisch-onderzoek.pdf"
    assert fm["hash"] == index.digest(folder / PDF)  # the bytes it was read from
    assert fm["pages"] == "1"
    assert body.startswith("## p1")


def test_a_replaced_document_shows_no_stale_text(client: TestClient) -> None:
    """The bytes behind the text change, so the row goes quiet rather than lie."""
    folder = _folder()
    documents.extract_folder(folder)
    (folder / PDF).write_bytes(_blank_pdf())

    row = next(d for d in documents.documents_of(folder, zaak.load(folder)) if d.name == ONDERZOEK)

    assert row.pages == 0  # not read yet, as far as these bytes are concerned
    assert not row.warn


def test_the_summary_of_a_document_lives_beside_it_in_the_zaak(client: TestClient) -> None:
    """A summary is part of the case, so it sits next to the document it describes."""
    documents.extract_folder(_folder())
    _store_summary(ZAAK, "ecologisch-onderzoek.pdf", "Onderzoek naar vleermuizen.")

    sidecar = _folder() / f"{PDF}.samenvatting.md"
    fm, body = schema.parse(sidecar.read_text("utf8"))

    assert fm["document"] == "ecologisch-onderzoek.pdf"
    assert fm["hash"] == index.digest(_folder() / PDF)  # the bytes it was written from
    assert body == "Onderzoek naar vleermuizen."


def test_a_replaced_document_shows_no_stale_summary(client: TestClient) -> None:
    """The file behind a summary changes, so the row goes quiet rather than lie."""
    documents.extract_folder(_folder())
    _store_summary(ZAAK, "ecologisch-onderzoek.pdf", "Onderzoek naar vleermuizen.")

    (_folder() / PDF).write_bytes(_blank_pdf())  # same name, different bytes

    assert "Onderzoek naar vleermuizen." not in client.get(f"/zaken/{ZAAK}").text


def test_a_summary_is_not_listed_as_an_attachment(client: TestClient) -> None:
    """The summary lies in the entry folder, but it is never a file of the case."""
    documents.extract_folder(_folder())
    _store_summary(ZAAK, "ecologisch-onderzoek.pdf", "Onderzoek naar vleermuizen.")

    entry = next(e for e in zaak.load(_folder()).log_entries if "hulpvraag" in e.name)

    assert (_folder() / f"{PDF}.samenvatting.md").is_file()  # it is on disk...
    assert not [a for a in entry.attachments if a.endswith(".samenvatting.md")]  # ...but not a file
    assert "samenvatting.md" not in client.get(f"/zaken/{ZAAK}").text


def test_storing_a_summary_writes_an_audit_line(client: TestClient) -> None:
    """A summary is a write to the zaak, so the trail records who made it."""
    documents.extract_folder(_folder())
    _store_summary(ZAAK, "ecologisch-onderzoek.pdf", "Onderzoek naar vleermuizen.")

    trail = (_folder() / "audit.log").read_text("utf8")

    assert "ecologisch-onderzoek.pdf" in trail.splitlines()[-1]
    assert "[agent]" in trail.splitlines()[-1]


def test_the_command_that_prints_text_never_writes_a_summary(client: TestClient) -> None:
    """`index text` reads. Only `index summary --set` writes, and the names say so."""
    documents.extract_folder(_folder())

    CliRunner().invoke(cli.app, ["index", "text", ZAAK])

    assert list(_folder().glob("log/*/*.samenvatting.md")) == []


def test_the_printed_text_of_a_document_holds_no_frontmatter(client: TestClient) -> None:
    """The agent asked for the text of a document, so it gets the pages and nothing else."""
    documents.extract_folder(_folder())

    result = CliRunner().invoke(cli.app, ["index", "text", ZAAK])

    assert result.exit_code == 0, result.output
    assert "extracted_at" not in result.output
    assert "---" not in result.output


def test_the_index_lists_each_document_with_its_pages_and_its_summary(
    client: TestClient,
) -> None:
    """The list says what the model holds, so a person sees what still needs reading."""
    folder = _folder()
    documents.extract_folder(folder)
    _store_summary(ZAAK, "ecologisch-onderzoek.pdf", "Onderzoek naar vleermuizen.")

    result = CliRunner().invoke(cli.app, ["index", "list", ZAAK])

    assert result.exit_code == 0, result.output
    rows = {line.split()[1]: line.split()[2:] for line in result.output.splitlines()[1:]}
    assert rows["ecologisch-onderzoek.pdf"] == ["1", "yes"]
    assert rows["definitief-besluit.pdf"] == ["1", "-"]


def test_a_jurist_asks_for_a_summary_and_the_page_reads_it_back(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A jurist presses the button on one document, and the zaak page shows what came back."""
    use_ai(tmp_path, monkeypatch, reply="Onderzoek naar vleermuizen in het plangebied.")
    documents.extract_folder(_folder())

    client.post(_ai_url(), follow_redirects=False)
    _wait_until_done(client)

    assert "Onderzoek naar vleermuizen in het plangebied." in client.get(f"/zaken/{ZAAK}").text


def test_the_button_under_a_logboek_item_asks_for_the_summary(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A jurist summarises a document where it was filed, without scrolling further."""
    use_ai(tmp_path, monkeypatch, reply="Onderzoek naar vleermuizen in het plangebied.")
    documents.extract_folder(_folder())
    assert _ai_url() in _logboek(client.get(f"/zaken/{ZAAK}").text)

    client.post(_ai_url(), follow_redirects=False)
    _wait_until_done(client)

    logboek = _logboek(client.get(f"/zaken/{ZAAK}").text)
    assert "Onderzoek naar vleermuizen in het plangebied." in logboek


def test_a_summary_the_app_made_sits_beside_the_document(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The app writes where a person writes: in the zaak, next to the file it describes."""
    use_ai(tmp_path, monkeypatch, reply="Onderzoek naar vleermuizen.")
    documents.extract_folder(_folder())

    client.post(_ai_url(), follow_redirects=False)
    _wait_until_done(client)

    stored = (_folder() / f"{PDF}.samenvatting.md").read_text("utf8")
    assert "Onderzoek naar vleermuizen." in schema.parse(stored)[1]


def test_asking_for_a_summary_writes_an_audit_line_naming_who_asked(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A summary is a write to the zaak, so the trail records the person who paid for it."""
    use_ai(tmp_path, monkeypatch)
    documents.extract_folder(_folder())

    client.post(_ai_url(), follow_redirects=False)
    _wait_until_done(client)

    last = (_folder() / "audit.log").read_text("utf8").splitlines()[-1]
    assert ONDERZOEK in last
    assert TEAMLID in last


def test_a_document_being_read_says_so_on_its_row(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While the model runs the row says it is busy, so nobody presses a second time."""
    use_ai(tmp_path, monkeypatch)
    started, release = threading.Event(), threading.Event()

    def slow_ask(system: str, document: str, text: str) -> str:
        started.set()
        release.wait(10)
        return "Klaar."

    monkeypatch.setattr("odas.ai.ask", slow_ask)
    documents.extract_folder(_folder())

    client.post(_ai_url(), follow_redirects=False)
    assert started.wait(10), "the worker never reached the model"
    busy = client.get(f"/zaken/{ZAAK}").text
    release.set()
    _wait_until_done(client)

    assert "bezig" in busy.lower()


def test_a_model_that_fails_leaves_no_summary_and_the_row_says_why(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The provider refuses, the case goes on, and the row carries a reason, not a trace."""
    use_ai(tmp_path, monkeypatch)

    def broken_ask(system: str, document: str, text: str) -> str:
        raise RuntimeError("401 api key sk-geheim is invalid, request_id=req_123")

    monkeypatch.setattr("odas.ai.ask", broken_ask)
    documents.extract_folder(_folder())

    client.post(_ai_url(), follow_redirects=False)
    _wait_until_done(client)

    page = client.get(f"/zaken/{ZAAK}").text
    assert not (_folder() / f"{PDF}.samenvatting.md").exists()
    assert "Het model antwoordde niet" in page
    assert "sk-geheim" not in page  # the provider's own words stay in the log
    assert _ai_url() in page  # ...and the button is there to press again


def test_a_document_that_already_has_a_summary_offers_no_button(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nobody pays twice for the same document by accident."""
    use_ai(tmp_path, monkeypatch)
    documents.extract_folder(_folder())
    _store_summary(ZAAK, ONDERZOEK, "Onderzoek naar vleermuizen.")

    page = client.get(f"/zaken/{ZAAK}").text

    assert "Onderzoek naar vleermuizen." in page
    assert _ai_url() not in page
    assert _ai_url("definitief-besluit.pdf", entry="2026-05-18-A-IN-definitief-besluit") in page


def test_the_text_of_a_document_reaches_the_model_as_quoted_material(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A document arrives from anyone, so nothing written inside it is an instruction."""
    seen = use_ai(tmp_path, monkeypatch)
    documents.extract_folder(_folder())

    client.post(_ai_url(), follow_redirects=False)
    _wait_until_done(client)

    document, prompt = seen[0]
    assert document == ONDERZOEK
    assert "BEGIN DOCUMENT" in prompt and "END DOCUMENT" in prompt
    assert "instructie" in prompt.lower()  # the standing instruction to ignore its contents
    assert "Schrijf 3 tot 5 Nederlandse zinnen." in prompt  # the organisation's own words


def test_a_data_dir_without_an_ai_section_offers_no_button_and_no_command(
    client: TestClient,
) -> None:
    """No section, no button and no command: the shape the connector already has."""
    documents.extract_folder(_folder())

    page = client.get(f"/zaken/{ZAAK}").text
    result = CliRunner().invoke(cli.app, ["index", "summarize", ZAAK])

    assert _ai_url() not in page  # the zaak's own body still has a Samenvatting heading
    assert "Samenvatten met AI" not in page
    assert result.exit_code != 0


def test_the_indiener_sees_no_button(client: TestClient, tmp_path: Path) -> None:
    """Nobody without an account spends the organisation's money on a summary."""
    documents.extract_folder(_folder())

    page = client.get(f"/inzien-{token_of(ZAAK)}").text

    assert "doc-row" in page  # the same row the team reads...
    assert _ai_url() not in page  # ...without the button on it


def test_the_command_line_writes_the_summary_the_page_reads_back(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A jurist backfills a whole zaak from a terminal, and the page shows the result."""
    use_ai(tmp_path, monkeypatch, reply="Wat er in dit stuk staat.")
    documents.extract_folder(_folder())

    result = CliRunner().invoke(cli.app, ["index", "summarize", ZAAK, ONDERZOEK])

    assert result.exit_code == 0, result.output
    assert "Wat er in dit stuk staat." in client.get(f"/zaken/{ZAAK}").text


def test_a_document_whose_sidecar_name_the_filesystem_refuses_is_still_a_row(
    client: TestClient,
) -> None:
    """A name too long to carry a summary beside it is a quiet row, never an error page."""
    # 250 bytes: the document fits, but the sidecar it would need does not.
    long_name = "x" * (250 - len(".pdf")) + ".pdf"
    entry_dir = _folder() / "log" / ENTRY
    (entry_dir / long_name).write_bytes((_folder() / PDF).read_bytes())

    response = client.get(f"/zaken/{ZAAK}")

    assert response.status_code == 200
    assert long_name in response.text


def test_pressing_the_button_on_an_unstorable_name_says_so(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A summary that cannot be written names the reason, and costs nothing to find out."""
    use_ai(tmp_path, monkeypatch)
    # Long enough that the summary suffix will not fit, short enough that the
    # text beside it still does, atomic write included: this is about the summary.
    long_name = "y" * (242 - len(".pdf")) + ".pdf"
    (_folder() / "log" / ENTRY / long_name).write_bytes((_folder() / PDF).read_bytes())
    documents.extract_folder(_folder())

    client.post(_ai_url(long_name), follow_redirects=False)
    _wait_until_done(client)

    page = client.get(f"/zaken/{ZAAK}").text
    assert "te lang" in page
    assert _ai_url(long_name) in page  # ...and the button is still there


def test_a_text_file_that_names_no_bytes_is_not_trusted(client: TestClient) -> None:
    """A text file whose hash is missing cannot be tied to the document, so it is unread."""
    folder = _folder()
    documents.extract_folder(folder)
    (folder / f"{PDF}.tekst.md").write_text("## p1\n\nEcologisch onderzoek\n", "utf8")

    row = next(d for d in documents.documents_of(folder, zaak.load(folder)) if d.name == ONDERZOEK)

    assert row.pages == 0
    assert not row.warn


def test_a_document_without_a_text_layer_is_never_sent_to_the_model(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan has nothing to read, so it costs nothing and its row keeps its warning."""
    seen = use_ai(tmp_path, monkeypatch)
    base = f"/zaken/{ZAAK}"
    post_log(client, base, "scan", "scan.pdf", _blank_pdf())

    entry = next(e.name for e in zaak.load(_folder()).log_entries if "scan" in e.name)
    client.post(_ai_url("scan.pdf", entry=entry), follow_redirects=False)
    _wait_until_done(client)

    assert seen == []
    assert documents.NO_TEXT in client.get(base).text


def test_a_summary_fits_beside_an_attachment_with_the_longest_allowed_name(
    client: TestClient,
) -> None:
    """A document keeps room for its summary, so the button never fails on the name."""
    long_name = "beantwoording-artikel-44-vragen-d66-" * 6 + "19-11-2024.pdf"
    entry = log_write.create_log_entry(
        _folder(LEEG),
        "IN",
        "2026-05-20",
        "---\nonderwerp: stukken\n---\n\nOntvangen.\n",
        attachments=[(long_name, b"%PDF-1.4 ")],
    )
    document = next(p for p in entry.iterdir() if p.suffix == ".pdf")

    index.write_summary(document, index.digest(document), "Vragen van D66.", TEAMLID)
    sidecar = index.summary_path(document)

    assert index.summary_of(document, index.digest(document)) == "Vragen van D66."
    assert len(sidecar.name) <= 143  # a volume that encrypts its filenames allows no more
