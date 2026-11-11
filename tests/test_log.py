"""The log: one file per thing that happened, named for when and which way.

Date and direction live in the *name*, never in the frontmatter, so the folder
sorts correctly in any file browser and stays readable without the tool. An
entry becomes a folder the moment it has an attachment, and keeps its name.

Sending mail is the same act as writing an entry, not a separate feature.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import (
    LEEG,
    SOLO_LEEG,
    SOLO_ZAAK,
    ZAAK,
    eml_files,
    post_log,
    read_msg,
    use_example_data,
    use_outbox,
    write_config,
)
from fastapi.testclient import TestClient

from odas import log_write, mail, mailin_store, zaak

BASE = f"/zaken/{LEEG}"  # an example zaak with no log yet


def _folder() -> Path:
    folder = zaak.find(LEEG)
    assert folder is not None
    return folder


def log_form(html: str) -> str:
    """The new-entry form of the page, whatever else the page draws."""
    found = re.search(r'<form[^>]*id="log-form".*?</form>', html, re.S)
    assert found is not None
    return found.group(0)


def form_actions(form: str) -> str:
    """The row of buttons that ends a form."""
    found = re.search(r'<div class="form-actions">.*?</div>', form, re.S)
    assert found is not None
    return found.group(0)


def route_line(html: str) -> str:
    """The correspondents line above one entry, as a person reads it."""
    found = re.search(r'<span class="route">(.*?)</span>', html, re.S)
    assert found is not None
    return " ".join(found.group(1).split())


# ── Writing entries ───────────────────────────────────────────────────────────


def test_creating_an_entry_writes_a_named_file(client: TestClient) -> None:
    r = client.post(
        f"{BASE}/log",
        data={
            "direction": "IN",
            "entry_date": "2026-05-20",
            "onderwerp": "telefoon",
            "body": "Gebeld over de termijn.",
        },
        files=[("documenten", ("notitie.txt", b"hallo", "text/plain"))],
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == BASE

    z = zaak.load(_folder())
    assert len(z.log_entries) == 1
    entry = z.log_entries[0]
    assert entry.name == "2026-05-20-A-IN-telefoon"  # date, letter, direction, slug
    assert entry.direction == "IN"
    assert entry.frontmatter["onderwerp"] == "telefoon"
    assert entry.body == "Gebeld over de termijn."
    assert [p.split("/")[-1] for p in entry.attachments] == ["notitie.txt"]
    assert "telefoon" in z.history


def test_writing_an_entry_stamps_the_zaak_as_changed(client: TestClient) -> None:
    """The overview sorts on the last change, so a note moves its zaak up."""
    client.post(
        f"{BASE}/log",
        data={"direction": "LOG", "entry_date": "2026-05-20", "onderwerp": "notitie", "body": "x"},
    )

    stamp = zaak.load(_folder()).frontmatter["gewijzigd"]
    # the moment of writing, not the entry date; the stamp on disk is UTC
    assert stamp.startswith(datetime.now(UTC).date().isoformat())


def test_the_picker_date_drives_the_name_not_today(client: TestClient) -> None:
    r = post_log(client, BASE, entry_date="2025-01-03", onderwerp="notitie", body="Achteraf.")
    assert r.status_code == 303

    entry = zaak.load(_folder()).log_entries[0]
    assert entry.datum == "2025-01-03"
    assert entry.name == "2025-01-03-A-LOG-notitie"
    assert "datum" not in entry.frontmatter  # the date is in the name, and only there


def test_an_onderwerp_with_a_colon_survives_the_round_trip(client: TestClient) -> None:
    log_write.write_log_entry(_folder(), "IN", "Fw: ecologisch rapport", "body", datum="2026-01-15")
    entry = zaak.load(_folder()).log_entries[0]
    assert entry.datum == "2026-01-15"
    assert entry.frontmatter["onderwerp"] == "Fw: ecologisch rapport"  # YAML-escaped on disk


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"direction": "LOG", "entry_date": "03-01-2025", "body": "x"}, "datum"),
        ({"direction": "ZIJWAARTS", "entry_date": "2026-05-20", "body": "x"}, "richting"),
    ],
)
def test_a_bad_entry_is_refused_and_writes_nothing(
    client: TestClient, data: dict[str, str], expected: str
) -> None:
    r = client.post(f"{BASE}/log", data=data)
    assert r.status_code == 422
    assert expected in r.text.lower()
    assert zaak.load(_folder()).log_entries == []


def test_a_typed_log_entry_names_the_person_who_typed_it(client: TestClient) -> None:
    """A note typed on the page carries the name of its author, not only an address."""
    post_log(client, BASE, onderwerp="telefoon", body="Gebeld met de gemeente.")

    entry = zaak.load(_folder()).log_entries[0]
    assert entry.frontmatter["van"] == "T test <test@example.com>"  # the name the directory holds


def test_the_log_line_of_a_note_reads_as_a_name(client: TestClient) -> None:
    """A person reads who filed the note; the address stays on disk."""
    post_log(client, BASE, onderwerp="telefoon", body="Gebeld met de gemeente.")

    assert route_line(client.get(BASE).text) == "T test"


def test_an_entry_written_by_a_script_names_no_author(client: TestClient) -> None:
    """`api` is a word, not a person, so nothing is put where an address belongs."""
    log_write.write_log_entry(_folder(), "LOG", "notitie", "Tekst.", by="api")

    assert zaak.load(_folder()).log_entries[0].frontmatter["van"] == ""


def test_editing_an_entry_keeps_its_name(client: TestClient) -> None:
    name = log_write.create_log_entry(
        _folder(), "LOG", "2026-05-20", "---\nonderwerp: notitie\n---\n\nEerst.\n"
    ).stem

    assert "Eerst." in client.get(f"{BASE}/log/{name}/bewerken").text
    r = client.post(
        f"{BASE}/log/{name}/bewerken", data={"body": "Aangepast."}, follow_redirects=False
    )
    assert r.status_code == 303

    entry = zaak.load(_folder()).log_entries[0]
    assert entry.body == "Aangepast."
    assert entry.name == name  # the name is identity, fixed at creation


def test_the_direction_of_an_entry_can_change_after_the_fact(client: TestClient) -> None:
    """A note filed as LOG by mistake becomes UIT; the text and the files come along."""
    name = log_write.create_log_entry(
        _folder(),
        "LOG",
        "2026-05-20",
        "---\nonderwerp: brief\n---\n\nVerzonden.\n",
        attachments=[("brief.txt", b"data")],
    ).stem
    assert '<select name="direction"' in client.get(f"{BASE}/log/{name}/bewerken").text

    r = client.post(
        f"{BASE}/log/{name}/bewerken",
        data={"body": "Verzonden.", "onderwerp": "brief", "direction": "UIT"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    (entry,) = zaak.load(_folder()).log_entries
    assert entry.direction == "UIT"
    assert entry.name == name.replace("-LOG-", "-UIT-")  # the direction is part of the name
    assert entry.body == "Verzonden."
    assert [a.split("/")[-1] for a in entry.attachments] == ["brief.txt"]
    assert not (_folder() / "log" / name).exists()  # nothing left under the old name


def test_a_flat_entry_becomes_a_folder_on_its_first_attachment(client: TestClient) -> None:
    """Promotion is invisible: same name, same URL, one more file inside."""
    name = log_write.create_log_entry(
        _folder(), "LOG", "2026-05-20", "---\nonderwerp: notitie\n---\n\nNotitie.\n"
    ).stem
    assert (_folder() / "log" / f"{name}.md").is_file()

    r = client.post(
        f"{BASE}/log/{name}/bewerken",
        data={"body": "Notitie."},
        files=[("documenten", ("bijlage.txt", b"data", "text/plain"))],
        follow_redirects=False,
    )
    assert r.status_code == 303

    entry = zaak.load(_folder()).log_entries[0]
    assert entry.name == name
    assert entry.attachments == [f"log/{name}/bijlage.txt"]
    assert not (_folder() / "log" / f"{name}.md").exists()
    assert (_folder() / "log" / name / "index.md").is_file()


def test_an_attachment_can_be_removed_again(client: TestClient) -> None:
    name = log_write.create_log_entry(
        _folder(),
        "LOG",
        "2026-05-20",
        "---\nonderwerp: notitie\n---\n\nNotitie.\n",
        attachments=[("weg.txt", b"a"), ("blijft.txt", b"b")],
    ).name

    r = client.post(
        f"{BASE}/log/{name}/bewerken",
        data={"body": "Notitie.", "verwijder": "weg.txt"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    entry = zaak.load(_folder()).log_entries[0]
    assert [p.split("/")[-1] for p in entry.attachments] == ["blijft.txt"]


def test_an_unknown_entry_is_a_404(client: TestClient) -> None:
    assert client.get(f"{BASE}/log/2026-01-01-A-LOG-nope/bewerken").status_code == 404


# ── Showing the text ──────────────────────────────────────────────────────────


def _shown(client: TestClient) -> str:
    """The block the zaak page draws the text of the first entry in."""
    return client.get(BASE).text.split('class="entry-text')[1].split("</div>")[0]


def test_the_text_of_an_entry_is_shown_as_it_was_written(client: TestClient) -> None:
    """Mail is not Markdown, so a numbered line and a star stay what the sender typed."""
    body = "Vraag 3.\n\n3. derde punt\n\n* geen nadruk *"
    assert post_log(client, BASE, onderwerp="notitie", body=body).status_code == 303

    shown = _shown(client)
    assert "3. derde punt" in shown
    assert "* geen nadruk *" in shown
    assert "<li>" not in shown  # no list was made out of the numbered line
    assert "<em>" not in shown  # and no emphasis out of the stars


def test_a_typed_line_break_stays_a_line_break(client: TestClient) -> None:
    """Two typed lines stay two lines; the page keeps the whitespace instead of marking it."""
    body = "Eerste regel.\nTweede regel."
    assert post_log(client, BASE, onderwerp="notitie", body=body).status_code == 303

    shown = _shown(client)
    assert "Eerste regel." in shown
    assert "Tweede regel." in shown
    assert "<br" not in shown
    assert "prewrap" in shown.split(">")[0]  # the class that draws the newline itself


# ── Deleting entries ──────────────────────────────────────────────────────────


def _an_entry(
    onderwerp: str = "notitie", attachments: list[tuple[str, bytes]] | None = None
) -> str:
    """Write one entry on LEEG and return its name."""
    return log_write.create_log_entry(
        _folder(),
        "LOG",
        "2026-05-20",
        f"---\nonderwerp: {onderwerp}\n---\n\nNotitie.\n",
        attachments=attachments,
    ).stem


def test_a_deleted_entry_leaves_the_zaak_page(client: TestClient) -> None:
    """The entry is off the page, and the log around it is untouched."""
    weg = _an_entry("weg")
    blijft = _an_entry("blijft")

    r = client.post(f"{BASE}/log/{weg}/verwijderen", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == BASE

    assert [e.name for e in zaak.load(_folder()).log_entries] == [blijft]
    page = client.get(BASE).text
    assert f"/log/{weg}/" not in page  # the entry is off the page
    assert "verwijderd (LOG): weg" in page  # the audit trail explains the gap


def test_a_deleted_entry_is_readable_in_the_prullenbak(client: TestClient) -> None:
    """Delete is a move: the text and the attachment are still there to read."""
    name = _an_entry("weg", attachments=[("brief.txt", b"de inhoud")])

    assert client.post(f"{BASE}/log/{name}/verwijderen", follow_redirects=False).status_code == 303

    entry = _folder() / "prullenbak" / name
    assert "onderwerp: weg" in (entry / "index.md").read_text(encoding="utf8")
    assert (entry / "brief.txt").read_bytes() == b"de inhoud"
    assert not (_folder() / "log" / name).exists()


def test_deleting_an_entry_is_recorded_in_the_audit_trail(client: TestClient) -> None:
    """The case file says who removed what, so the gap in the log is explained."""
    name = _an_entry("weg")
    client.post(f"{BASE}/log/{name}/verwijderen")

    history = zaak.load(_folder()).history
    assert "verwijderd" in history
    assert "weg" in history
    assert "test@example.com" in history  # the identity ODAS_TEST_MODE acts as


def test_the_prullenbak_keeps_both_entries_that_want_the_same_name(client: TestClient) -> None:
    """Deleting an entry frees its letter, so the next one can mint the same name."""
    first = _an_entry("notitie")
    client.post(f"{BASE}/log/{first}/verwijderen")
    second = _an_entry("notitie")
    assert second == first  # the letter came free again
    client.post(f"{BASE}/log/{second}/verwijderen")

    kept = sorted(p.name for p in (_folder() / "prullenbak").iterdir())
    assert kept == [f"{first}-2.md", f"{first}.md"]  # the number keeps both


def test_the_confirm_step_names_the_entry_and_counts_its_attachments(client: TestClient) -> None:
    """A person reads what goes and where it goes before anything moves."""
    name = _an_entry("besluit", attachments=[("a.txt", b"a"), ("b.txt", b"b")])

    body = client.get(f"{BASE}/log/{name}/verwijderen").text
    assert "besluit" in body
    assert "2 bijlagen" in body
    assert "prullenbak" in body
    assert zaak.load(_folder()).log_entries[0].name == name  # a look changes nothing


def test_only_the_edit_page_offers_the_delete_action(client: TestClient) -> None:
    """The pages a person reads all day carry no destructive control."""
    name = _an_entry("notitie")
    action = f"{BASE}/log/{name}/verwijderen"

    assert action not in client.get(BASE).text
    assert action in client.get(f"{BASE}/log/{name}/bewerken").text


def test_deleting_an_unknown_entry_is_a_404(client: TestClient) -> None:
    assert client.post(f"{BASE}/log/2026-01-01-A-LOG-nope/verwijderen").status_code == 404


# ── Serving attachments ───────────────────────────────────────────────────────


def test_an_attachment_is_served_inline(client: TestClient) -> None:
    name = log_write.create_log_entry(
        _folder(),
        "LOG",
        "2026-05-20",
        "---\nonderwerp: notitie\n---\n\nNotitie.\n",
        attachments=[("besluit.pdf", b"%PDF-1.4 fake")],
    ).name

    r = client.get(f"{BASE}/log/{name}/bijlage/besluit.pdf")
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 fake"
    assert "inline" in r.headers["content-disposition"]


def test_an_attached_web_page_downloads_and_never_runs_on_the_site(client: TestClient) -> None:
    """An indiener can attach any file, so a web page is saved, not opened as ours."""
    name = log_write.create_log_entry(
        _folder(),
        "IN",
        "2026-05-20",
        "---\nonderwerp: reactie\n---\n\nZie bijlage.\n",
        attachments=[("pagina.html", b"<script>fetch('/zaken')</script>")],
    ).name

    r = client.get(f"{BASE}/log/{name}/bijlage/pagina.html")
    assert r.content == b"<script>fetch('/zaken')</script>"
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["content-security-policy"] == "sandbox"  # no script, even if opened
    assert r.headers["x-content-type-options"] == "nosniff"


def test_a_mail_entry_lists_its_documents_and_not_the_message_itself(
    client: TestClient,
) -> None:
    """The logboek names the documents of a message; the message is the .eml link."""
    name = log_write.create_log_entry(
        _folder(),
        "IN",
        "2026-05-20",
        "---\nonderwerp: brief\nvan: griffie@gemeente.example.nl\nmessage_id: <brief-1@gemeente.example.nl>\n---\n\nBrief.\n",
        attachments=[
            ("bericht.eml", b"From: griffie@gemeente.example.nl"),
            ("bezwaar.pdf", b"%PDF-1.4"),
        ],
    ).name

    page = client.get(BASE).text

    assert "bezwaar.pdf" in page
    assert f"{BASE}/log/{name}/bijlage/bericht.eml" in page
    assert page.count("bericht.eml") == 1  # the .eml link, and no document row of its own


@pytest.mark.parametrize(
    ("filename", "why"),
    [
        ("..%2F..%2Findex.md", "path traversal must not escape the entry"),
        ("nope.pdf", "a file that is not there"),
    ],
)
def test_an_attachment_request_that_resolves_to_nothing_is_a_404(
    client: TestClient, filename: str, why: str
) -> None:
    name = log_write.create_log_entry(
        _folder(), "LOG", "2026-05-20", "---\nonderwerp: notitie\n---\n\nx.\n"
    ).name
    assert client.get(f"{BASE}/log/{name}/bijlage/{filename}").status_code == 404, why


# ── Sending ───────────────────────────────────────────────────────────────────


def test_mail_send_writes_an_eml_to_the_outbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox = use_outbox(tmp_path)
    mail.send(["a@example.org"], "Onderwerp", "Tekst.")

    msg = read_msg(eml_files(outbox)[0])
    assert msg["To"] == "a@example.org"
    assert msg["Subject"] == "Onderwerp"
    assert "Tekst." in msg.get_content()


def test_mail_send_without_a_configured_host_reports_failure(tmp_path: Path) -> None:
    """An empty `smtp.host` means nothing is sent, and the caller is told so."""
    with pytest.raises(mail.MailError, match="mailtransport"):
        mail.send(["a@example.org"], "s", "body")


def test_the_sender_and_transport_come_from_the_configuration_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SMTP settings moved into the data dir, so stale mail env vars change nothing."""
    outbox = use_outbox(tmp_path)
    monkeypatch.setenv("SMTP_HOST", str(tmp_path / "wrong"))
    monkeypatch.setenv("SMTP_FROM", "env@example.org")
    mail.send(["a@example.org"], "Onderwerp", "Tekst.")

    assert not (tmp_path / "wrong").exists()  # the env var named no transport
    assert read_msg(eml_files(outbox)[0])["From"] == "noreply@localhost"  # template default


def test_a_log_entry_carries_no_recipient_when_the_data_dir_never_mails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The solo jurist's log records what happened; it is not an outbox."""
    use_example_data("solo", tmp_path, monkeypatch)
    folder = zaak.find(SOLO_LEEG)
    assert folder is not None

    log_write.write_log_entry(folder, "LOG", "Dossier doorgenomen", "Notitie.", by="a.jansen")

    entry = zaak.load(folder).log_entries[-1]
    assert "aan" not in entry.frontmatter  # not declared, so not written


# ── Sending an entry as mail ──────────────────────────────────────────────────


def _send(client: TestClient, **fields: str) -> Any:
    """Press "Verstuur e-mail" on the new-entry form of the empty zaak."""
    data = {
        "direction": "UIT",
        "entry_date": "2026-05-20",
        "onderwerp": "Uw hulpvraag",
        "body": "We kijken ernaar.",
        "action": "send",
    }
    data.update(fields)
    return client.post(f"{BASE}/log", data=data, follow_redirects=False)


def test_sending_a_log_entry_mails_the_text_and_files_it(
    client: TestClient, tmp_path: Path
) -> None:
    """One act: the text goes out as e-mail and stays in the zaak as a log entry."""
    outbox = use_outbox(tmp_path)

    assert _send(client, aan="b@example.org").status_code == 303

    msg = read_msg(eml_files(outbox)[0])
    assert msg["To"] == "b@example.org"
    assert str(msg["Subject"]) == "Uw hulpvraag"
    assert "We kijken ernaar." in msg.get_content()
    assert msg["Reply-To"] == f"{LEEG}@odas.veenwacht.example.nl"  # an answer files itself here

    entry = zaak.load(_folder()).log_entries[-1]
    assert entry.direction == "UIT"
    assert entry.frontmatter["aan"] == "b@example.org"
    assert entry.body == "We kijken ernaar."


def test_the_mail_carries_the_name_of_the_person_who_writes_it(
    client: TestClient, tmp_path: Path
) -> None:
    """The recipient reads the address of the organisation, with the writer's name."""
    outbox = use_outbox(tmp_path)

    assert _send(client, aan="b@example.org").status_code == 303

    # "T test" is the name the directory holds; the address is the data dir's own.
    assert (
        read_msg(eml_files(outbox)[0])["From"] == "T test <noreply@hulpvraag.veenwacht.example.nl>"
    )


def test_a_cc_recipient_gets_the_mail_and_stands_in_the_entry(
    client: TestClient, tmp_path: Path
) -> None:
    outbox = use_outbox(tmp_path)

    assert _send(client, aan="b@example.org", cc="c@example.org, d@example.org").status_code == 303

    msg = read_msg(eml_files(outbox)[0])
    assert msg["Cc"] == "c@example.org, d@example.org"
    assert zaak.load(_folder()).log_entries[-1].frontmatter["cc"] == "c@example.org, d@example.org"


def test_a_mail_to_a_colleague_stays_an_internal_note(client: TestClient, tmp_path: Path) -> None:
    """The direction is the writer's own choice: a LOG item may still be sent."""
    outbox = use_outbox(tmp_path)

    assert _send(client, direction="LOG", aan="collega@example.org").status_code == 303

    assert read_msg(eml_files(outbox)[0])["To"] == "collega@example.org"
    assert zaak.load(_folder()).log_entries[-1].direction == "LOG"


def test_a_sent_entry_carries_the_message_that_went(client: TestClient, tmp_path: Path) -> None:
    """The proof of sending is the message itself, kept beside the entry as `bericht.eml`."""
    use_outbox(tmp_path)

    assert _send(client, aan="b@example.org", cc="c@example.org").status_code == 303

    entry = zaak.load(_folder()).log_entries[-1]
    proof = read_msg(_folder() / entry.attachments[0])
    assert entry.attachments == [f"log/{entry.name}/bericht.eml"]
    assert proof["To"] == "b@example.org"
    assert proof["Cc"] == "c@example.org"
    assert "We kijken ernaar." in proof.get_content()
    # The identifier ties the entry to the bytes, the way a received entry is tied.
    assert entry.frontmatter["message_id"] == proof["Message-ID"]


def test_the_zaak_page_offers_the_sent_message_for_download(
    client: TestClient, tmp_path: Path
) -> None:
    """A sent entry reads like a received one: the same link, to the same file name."""
    use_outbox(tmp_path)
    assert _send(client, aan="b@example.org").status_code == 303

    name = zaak.load(_folder()).log_entries[-1].name
    assert f"{BASE}/log/{name}/bijlage/bericht.eml" in client.get(BASE).text

    r = client.get(f"{BASE}/log/{name}/bijlage/bericht.eml")
    assert r.status_code == 200
    assert "We kijken ernaar." in r.text


def test_a_sent_entry_mails_its_documents_and_keeps_them(
    client: TestClient, tmp_path: Path
) -> None:
    """A file added to the entry goes out with the mail and stays in the zaak."""
    outbox = use_outbox(tmp_path)

    r = client.post(
        f"{BASE}/log",
        data={
            "direction": "UIT",
            "entry_date": "2026-05-20",
            "onderwerp": "Uw hulpvraag",
            "body": "We kijken ernaar.",
            "action": "send",
            "aan": "b@example.org",
        },
        files=[("documenten", ("bijlage.txt", b"hallo", "text/plain"))],
        follow_redirects=False,
    )
    assert r.status_code == 303

    sent = read_msg(eml_files(outbox)[0])
    carried = {p.get_filename(): p.get_payload(decode=True) for p in sent.iter_attachments()}
    assert carried == {"bijlage.txt": b"hallo"}

    entry = zaak.load(_folder()).log_entries[-1]
    assert sorted(a.split("/")[-1] for a in entry.attachments) == ["bericht.eml", "bijlage.txt"]


def test_a_send_that_fails_writes_no_entry_and_names_the_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relay refuses, so nothing is filed and the person reads why."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise mail.MailError("relay.example.nl nam het bericht niet aan.")

    monkeypatch.setattr(mail, "send", refuse)

    r = _send(client, aan="b@example.org")

    assert r.status_code == 422
    assert "niet gelukt" in r.text
    assert "relay.example.nl nam het bericht niet aan." in r.text  # the reason, not a code
    assert "We kijken ernaar." in r.text  # the text is still in the form
    assert zaak.load(_folder()).log_entries == []


def test_sending_without_a_recipient_is_refused(client: TestClient, tmp_path: Path) -> None:
    """Press send with an empty Aan and the page says so, rather than filing in silence."""
    outbox = use_outbox(tmp_path)

    r = _send(client, aan="", cc="")

    assert r.status_code == 422
    assert "Aan of Cc" in r.text
    assert eml_files(outbox) == []
    assert zaak.load(_folder()).log_entries == []


def test_a_mail_addressed_only_in_cc_still_goes_out(client: TestClient, tmp_path: Path) -> None:
    """A Cc is a recipient. The button is on, so the send must work."""
    outbox = use_outbox(tmp_path)

    assert _send(client, aan="", cc="c@example.org").status_code == 303

    msg = read_msg(eml_files(outbox)[0])
    assert msg["Cc"] == "c@example.org"
    assert zaak.load(_folder()).log_entries[-1].frontmatter["cc"] == "c@example.org"


def test_saving_an_entry_with_a_recipient_sends_nothing(client: TestClient, tmp_path: Path) -> None:
    """Opslaan files the entry. Only Verstuur e-mail puts it on the wire."""
    outbox = use_outbox(tmp_path)

    assert _send(client, aan="b@example.org", action="").status_code == 303

    assert eml_files(outbox) == []
    assert zaak.load(_folder()).log_entries[-1].frontmatter["aan"] == "b@example.org"


def test_the_new_entry_form_shows_the_recipients_and_the_send_button(
    client: TestClient,
) -> None:
    """A person sees Aan, Cc and Verstuur e-mail at once. Nothing is folded away."""
    form = log_form(client.get(BASE).text)

    assert 'name="aan"' in form
    assert 'name="cc"' in form
    assert "Verstuur e-mail" in form
    assert "<details" not in form  # no folded box hides the recipients or the button


def test_the_send_button_stands_next_to_opslaan(client: TestClient) -> None:
    """One row of choices at the end of the form, so neither button hides."""
    actions = form_actions(log_form(client.get(BASE).text))

    assert "Verstuur e-mail" in actions
    assert ">Opslaan</button>" in actions
    assert "Annuleren" in actions


def test_the_send_button_is_off_while_the_form_holds_no_recipient(
    client: TestClient,
) -> None:
    """An empty form cannot mail anyone, so the button says so before it is pressed."""
    actions = form_actions(log_form(client.get(BASE).text))

    assert re.search(r"<button[^>]*btn-send[^>]*\bdisabled\b", actions)


def test_a_data_dir_that_declares_no_recipient_offers_no_sending(
    solo_client: TestClient,
) -> None:
    """Mail is a declaration like any other: no `aan` in fields.log, no button."""
    page = solo_client.get(f"/zaken/{SOLO_LEEG}").text

    assert "Verstuur e-mail" not in page
    assert 'name="aan"' not in page


def test_the_form_shows_the_footer_the_data_dir_declares(
    client: TestClient, tmp_path: Path
) -> None:
    """A person reads the footer, and the link in it, before pressing send."""
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["smtp"] = {**config["smtp"], "footer": "Bekijk uw zaak: {inzien_url}"}
    write_config(tmp_path, config)
    r = client.post("/zaken", data={"titel": "Nieuw", "soort": "hulpvraag"}, follow_redirects=False)

    page = client.get(r.headers["location"]).text

    assert "Bekijk uw zaak: http" in page
    assert "/inzien-" in page  # the token page of this zaak, not a placeholder


def test_the_footer_names_the_writer_and_the_address_of_the_zaak(
    client: TestClient, tmp_path: Path
) -> None:
    """A person signs with their own name, and points at the address of the zaak."""
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["smtp"] = {**config["smtp"], "footer": "Groet, {gebruiker} -- {zaak_adres}"}
    write_config(tmp_path, config)

    page = client.get(f"/zaken/{ZAAK}").text

    assert f"Groet, T test -- {ZAAK}@odas.veenwacht.example.nl" in page


def test_a_data_dir_without_mail_capture_leaves_the_address_empty(
    solo_client: TestClient, tmp_path: Path
) -> None:
    """No zaak address exists, so the footer shows the rest of its words."""
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["smtp"] = {"footer": "Groet, {gebruiker}. Adres: {zaak_adres}."}
    write_config(tmp_path, config)

    page = solo_client.get(f"/zaken/{SOLO_ZAAK}").text

    assert "Groet, T test. Adres: ." in page


# ── Mail templates the data dir owns ──────────────────────────────────────────


def test_the_confirmation_mail_uses_the_data_dirs_own_words(
    client: TestClient, tmp_path: Path
) -> None:
    """The message a submitter reads is the organisation's text, not the code's."""
    outbox = use_outbox(tmp_path)
    r = client.post(
        "/indienen",
        data={
            "titel": "Kap laanbomen",
            "omschrijving": "Veertig bomen.",
            "contact_naam": "A. de Vries",
            "contact_email": "b@example.org",
            "mail_toestemming": "nee",
        },
    )
    assert r.status_code == 200

    msg = read_msg(eml_files(outbox)[0])
    assert msg["To"] == "b@example.org"
    assert "Bevestiging van uw hulpvraag" in str(msg["Subject"])
    assert "Stichting Veenwacht" in msg.get_content()  # veenwacht's sign-off, from its config
    assert "zk-" in msg.get_content()  # the reference, filled into the template


def test_a_data_dir_that_declares_no_template_sends_that_mail_not_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mail is a declaration like any other: no template, no message."""
    use_example_data("solo", tmp_path, monkeypatch)
    outbox = use_outbox(tmp_path)

    assert (
        mail.send_template("intake_bevestiging", ["a@example.org"], values={"ref": "zk-1"}) is None
    )
    assert eml_files(outbox) == []


def test_a_note_written_where_nothing_is_sent_carries_no_mail_keys(
    solo_client: TestClient,
) -> None:
    """A stamp for when a message went out is meaningless where none ever does."""
    from conftest import SOLO_LEEG

    r = post_log(solo_client, f"/zaken/{SOLO_LEEG}", onderwerp="Overleg", body="Notitie.")
    assert r.status_code == 303

    entry = zaak.load(zaak.find(SOLO_LEEG)).log_entries[-1]  # type: ignore[arg-type]
    assert list(entry.frontmatter) == ["aangemaakt", "gewijzigd", "onderwerp"]  # no recipients
    assert entry.body == "Notitie."


# ── Long names ────────────────────────────────────────────────────────────────


def test_a_log_entry_with_a_very_long_onderwerp_gets_a_short_folder_name(
    client: TestClient,
) -> None:
    """A mail subject may run on; the name it makes on disk still fits any volume."""
    onderwerp = "Beantwoording van de artikel 44 vragen over het principeverzoek " * 5
    r = post_log(client, BASE, onderwerp=onderwerp, body="Ontvangen.")
    assert r.status_code == 303

    entry = zaak.load(_folder()).log_entries[0]
    assert len(entry.name) <= 117  # the 17 of date-letter-direction, plus a 100 slug
    assert entry.name.startswith("2026-05-20-A-LOG-beantwoording-van-de-artikel-44-vragen")


def test_an_attachment_with_a_very_long_name_is_stored_under_a_short_name(
    client: TestClient,
) -> None:
    """A person attaches a file with a very long name; the copy on disk is cut to fit."""
    long_name = "beantwoording-artikel-44-vragen-d66-" * 6 + "19-11-2024.pdf"
    r = client.post(
        f"{BASE}/log",
        data={"direction": "IN", "entry_date": "2026-05-20", "onderwerp": "stukken"},
        files=[("documenten", (long_name, b"%PDF-1.4 ", "application/pdf"))],
        follow_redirects=False,
    )
    assert r.status_code == 303

    entry = zaak.load(_folder()).log_entries[0]
    stored = Path(entry.attachments[0]).name
    assert len(stored) <= 104  # a 100 slug, plus the ".pdf" it keeps
    assert stored.startswith("beantwoording-artikel-44-vragen-d66-")
    assert stored.endswith(".pdf")


def test_the_recipient_box_takes_more_than_one_address(client: TestClient) -> None:
    """Aan and Cc hold a list, so the browser must accept the comma between them."""
    page = client.get(f"{BASE}").text

    for key in ("aan", "cc"):
        tag = next(t for t in page.split("<input ") if f'name="{key}"' in t)
        assert " multiple" in tag.split(">")[0]  # without it the browser refuses "a@x.nl, b@y.nl"


def _received_message(body: str = "Vóór 1 juni een reactie, alstublieft.") -> bytes:
    """What a mail client puts on the wire: an accented body and a PDF beside it."""
    msg = EmailMessage()
    msg["From"] = "griffie@gemeente.example.nl"
    msg["To"] = "m.dekker@veenwacht.example.nl"
    msg["Subject"] = "Uw bezwaarschrift"
    msg["Date"] = "Wed, 20 May 2026 09:14:00 +0200"
    msg["Message-ID"] = "<bezwaar-001@gemeente.example.nl>"
    msg["Received"] = "from relay.gemeente.example.nl by odas.example.nl"
    msg.set_content(body, cte="quoted-printable")  # as every mail client sends Dutch text
    msg.add_attachment(
        b"%PDF-1.4 " + b"x" * 4000, maintype="application", subtype="pdf", filename="bezwaar.pdf"
    )
    return msg.as_bytes()


def _file_message(raw: bytes) -> str:
    entry = mailin_store.file_message(_folder(), "IN", raw)
    assert entry is not None
    return entry.name


def test_the_eml_link_shows_the_message_as_it_was_sent(client: TestClient) -> None:
    """The window holds the message itself: its own headers, its text, its bijlagen."""
    name = _file_message(_received_message())

    r = client.get(f"{BASE}/log/{name}/bericht")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert (
        "Received: from relay.gemeente.example.nl by odas.example.nl" in r.text
    )  # never on the page
    assert "Message-ID: <bezwaar-001@gemeente.example.nl>" in r.text
    assert "Vóór 1 juni een reactie, alstublieft." in r.text  # decoded, not =C3=B3=C3=B3r
    assert "[bijlage: bezwaar.pdf" in r.text
    assert "JVBERi0" not in r.text  # the bytes of a bijlage stay out of the window


def test_the_window_reads_an_html_message_as_text(client: TestClient) -> None:
    """A message with no plain part reads as text, not as markup."""
    msg = EmailMessage()
    msg["From"] = "griffie@gemeente.example.nl"
    msg["Subject"] = "Stand van zaken"
    msg["Message-ID"] = "<html-1@gemeente.example.nl>"
    msg.set_content(
        "<html><body><p>Beste mevrouw,</p><p>Wij berichten u.</p></body></html>", subtype="html"
    )
    name = _file_message(msg.as_bytes())

    text = client.get(f"{BASE}/log/{name}/bericht").text

    assert "Beste mevrouw,\n\nWij berichten u." in text
    assert "<p>" not in text


def test_an_entry_without_a_message_has_nothing_to_show(client: TestClient) -> None:
    """A typed note is not a message, so there is no window to open."""
    name = log_write.create_log_entry(
        _folder(), "LOG", "2026-05-20", "---\nonderwerp: notitie\n---\n\nNotitie.\n"
    ).name

    assert client.get(f"{BASE}/log/{name}/bericht").status_code == 404


def test_a_message_request_that_leaves_the_entry_is_a_404(client: TestClient) -> None:
    """The window reads one entry folder and no other place on disk."""
    _file_message(_received_message())

    assert client.get(f"{BASE}/log/..%2F..%2F..%2Fetc/bericht").status_code == 404


def test_a_downloaded_message_is_named_after_the_zaak_and_the_entry(client: TestClient) -> None:
    """Two saved messages never collide: the name says which zaak and which item."""
    raw = _received_message()
    name = _file_message(raw)

    r = client.get(f"{BASE}/log/{name}/bijlage/bericht.eml")

    assert r.status_code == 200
    assert f'filename="{LEEG}-{name}.eml"' in r.headers["content-disposition"]
    assert r.content == raw  # the saved file is the message, byte for byte


def test_the_zaak_page_opens_the_message_and_still_offers_the_file(client: TestClient) -> None:
    """The .eml link opens the window; the file itself stays one click away in it."""
    name = _file_message(_received_message())

    page = client.get(BASE).text

    assert f'href="{BASE}/log/{name}/bericht"' in page
    assert f'data-eml="{BASE}/log/{name}/bijlage/bericht.eml"' in page
    assert 'data-onderwerp="Uw bezwaarschrift"' in page  # the window names the message
    assert 'id="eml-dialog"' in page


# ── Editing an entry that carries a message ───────────────────────────────────


def _edit_page(client: TestClient, name: str) -> str:
    return client.get(f"{BASE}/log/{name}/bewerken").text


def typeable(page: str, key: str) -> list[str]:
    """The controls on the page a person can type this disk key into."""
    found = re.findall(rf"<[^>]*name=\"{key}\"[^>]*>", page)
    return [c for c in found if 'type="hidden"' not in c]


def test_the_recipients_of_a_sent_entry_are_read_only(client: TestClient, tmp_path: Path) -> None:
    """The message is gone. Aan and Cc read as facts, so no field promises a change."""
    use_outbox(tmp_path)
    _send(client, aan="b@example.org", cc="c@example.org")
    name = zaak.load(_folder()).log_entries[-1].name

    page = _edit_page(client, name)

    assert typeable(page, "aan") == []  # the header is on the wire; no field offers a change
    assert typeable(page, "cc") == []
    assert "b@example.org" in page  # the address is still there to read
    assert "c@example.org" in page


def test_the_recipient_of_a_hand_recorded_entry_stays_editable(
    client: TestClient, tmp_path: Path
) -> None:
    """A message sent elsewhere is typed by a person, so a typo in Aan can be fixed."""
    use_outbox(tmp_path)
    _send(client, aan="b@example.org", action="")  # Opslaan: nothing went out
    name = zaak.load(_folder()).log_entries[-1].name

    assert typeable(_edit_page(client, name), "aan")

    r = client.post(
        f"{BASE}/log/{name}/bewerken",
        data={"body": "We kijken ernaar.", "onderwerp": "Uw hulpvraag", "aan": "goed@example.org"},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert zaak.load(_folder()).log_entries[-1].frontmatter["aan"] == "goed@example.org"


def test_editing_a_sent_entry_keeps_its_recipients(client: TestClient, tmp_path: Path) -> None:
    """A save cannot rewrite the headers of a message that already went out."""
    use_outbox(tmp_path)
    _send(client, aan="b@example.org", cc="c@example.org")
    name = zaak.load(_folder()).log_entries[-1].name

    r = client.post(
        f"{BASE}/log/{name}/bewerken",
        data={"body": "Aangepast.", "onderwerp": "Uw hulpvraag", "aan": "elders@example.org"},
        follow_redirects=False,
    )

    assert r.status_code == 303
    fm = zaak.load(_folder()).log_entries[-1].frontmatter
    assert fm["aan"] == "b@example.org"
    assert fm["cc"] == "c@example.org"


def _saved_entry(client: TestClient, **fields: str) -> str:
    """An entry typed with Opslaan, so nothing went out. Returns its name."""
    _send(client, action="", **fields)
    return zaak.load(_folder()).log_entries[-1].name


def test_an_entry_that_was_never_sent_can_go_out_from_the_editor(
    client: TestClient, tmp_path: Path
) -> None:
    """A person writes now and sends later. The same item goes; no second one appears."""
    outbox = use_outbox(tmp_path)
    name = _saved_entry(client, aan="b@example.org")

    r = client.post(
        f"{BASE}/log/{name}/bewerken",
        data={
            "onderwerp": "Uw hulpvraag",
            "body": "We kijken ernaar.",
            "aan": "b@example.org",
            "direction": "UIT",
            "action": "send",
        },
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert read_msg(eml_files(outbox)[0])["To"] == "b@example.org"
    (entry,) = zaak.load(_folder()).log_entries  # one item, not two
    assert entry.name == name
    assert entry.attachments == [f"log/{name}/bericht.eml"]  # the proof stands beside it
    assert entry.frontmatter["message_id"] == read_msg(eml_files(outbox)[0])["Message-ID"]


def test_the_editor_offers_the_send_button_until_the_message_is_gone(
    client: TestClient, tmp_path: Path
) -> None:
    """The button and the fields go together: both before sending, neither after."""
    use_outbox(tmp_path)
    saved = _saved_entry(client, aan="b@example.org")
    assert "Verstuur e-mail" in _edit_page(client, saved)

    _send(client, aan="b@example.org")
    sent = zaak.load(_folder()).log_entries[-1].name

    assert "Verstuur e-mail" not in _edit_page(client, sent)


def test_a_send_from_the_editor_that_fails_changes_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relay refuses, so the entry stays as it was and the person reads why."""
    name = _saved_entry(client, aan="b@example.org")

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise mail.MailError("relay.example.nl nam het bericht niet aan.")

    monkeypatch.setattr(mail, "send", refuse)
    r = client.post(
        f"{BASE}/log/{name}/bewerken",
        data={
            "onderwerp": "Uw hulpvraag",
            "body": "Toch anders.",
            "aan": "b@example.org",
            "direction": "UIT",
            "action": "send",
        },
    )

    assert r.status_code == 422
    assert "relay.example.nl nam het bericht niet aan." in r.text
    assert "Toch anders." in r.text  # the typed text is still in the form
    entry = zaak.load(_folder()).log_entries[-1]
    assert entry.body == "We kijken ernaar."  # nothing was written
    assert entry.attachments == []


def test_an_entry_is_never_sent_twice(client: TestClient, tmp_path: Path) -> None:
    """A stale page asks to send an item that already went. One message stays one."""
    outbox = use_outbox(tmp_path)
    _send(client, aan="b@example.org")
    name = zaak.load(_folder()).log_entries[-1].name

    r = client.post(
        f"{BASE}/log/{name}/bewerken",
        data={"onderwerp": "Uw hulpvraag", "body": "x.", "direction": "UIT", "action": "send"},
    )

    assert r.status_code == 422
    assert "al verstuurd" in r.text
    assert len(eml_files(outbox)) == 1


def _draft_with_file(client: TestClient, fname: str = "bijlage.txt") -> str:
    """Save an entry that has one document, ready to be sent later. Returns its name."""
    r = client.post(
        f"{BASE}/log",
        data={"direction": "UIT", "entry_date": "2026-05-20", "onderwerp": "Uw hulpvraag"},
        files=[("documenten", (fname, b"hallo", "text/plain"))],
        follow_redirects=False,
    )
    assert r.status_code == 303
    return zaak.load(_folder()).log_entries[-1].name


def test_sending_a_saved_entry_carries_the_documents_it_already_had(
    client: TestClient, tmp_path: Path
) -> None:
    """A file added before the send still reaches the recipient."""
    outbox = use_outbox(tmp_path)
    name = _draft_with_file(client)

    r = client.post(
        f"{BASE}/log/{name}/bewerken",
        data={
            "body": "Zie bijlage.",
            "onderwerp": "Uw hulpvraag",
            "aan": "b@example.org",
            "action": "send",
        },
        files=[("documenten", ("tweede.txt", b"ook", "text/plain"))],
        follow_redirects=False,
    )

    assert r.status_code == 303
    sent = read_msg(eml_files(outbox)[0])
    carried = {p.get_filename(): p.get_payload(decode=True) for p in sent.iter_attachments()}
    assert carried == {"bijlage.txt": b"hallo", "tweede.txt": b"ook"}


def test_a_document_removed_in_the_same_save_does_not_go_out(
    client: TestClient, tmp_path: Path
) -> None:
    """Tick the bin on a file and press send: the recipient never sees that file."""
    outbox = use_outbox(tmp_path)
    name = _draft_with_file(client)

    r = client.post(
        f"{BASE}/log/{name}/bewerken",
        data={
            "body": "Zonder bijlage.",
            "onderwerp": "Uw hulpvraag",
            "aan": "b@example.org",
            "action": "send",
            "verwijder": "bijlage.txt",
        },
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert list(read_msg(eml_files(outbox)[0]).iter_attachments()) == []
    assert zaak.load(_folder()).log_entries[-1].attachments == [f"log/{name}/bericht.eml"]


def test_a_send_that_fails_leaves_the_documents_of_the_entry_alone(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relay refuses, so the entry keeps the file it had and the text is returned."""
    name = _draft_with_file(client)

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise mail.MailError("relay.example.nl nam het bericht niet aan.")

    monkeypatch.setattr(mail, "send", refuse)
    r = client.post(
        f"{BASE}/log/{name}/bewerken",
        data={
            "body": "Zie bijlage.",
            "onderwerp": "Uw hulpvraag",
            "aan": "b@example.org",
            "action": "send",
        },
        follow_redirects=False,
    )

    assert r.status_code == 422
    assert "relay.example.nl nam het bericht niet aan." in r.text
    assert zaak.load(_folder()).log_entries[-1].attachments == [f"log/{name}/bijlage.txt"]
