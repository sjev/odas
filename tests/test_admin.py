"""The Admin page: a test mail, back-ups, and the audit and log tails.

The manual promises a team member one page for maintenance. What this file
proves is that the page is closed to everyone else, that a test mail is the
data dir's own template, that a backup is one zip that opens with the
password shown beside it and with nothing else, and that the audit trail
combines every zaak's history into one collapsible list.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pyzipper
from conftest import LEEG, TEAMLID, ZAAK, ZAAK_FOLDER, create_dossier, post_log, use_outbox
from fastapi.testclient import TestClient

PAGE = "/admin"


def backup_rows(html: str) -> list[tuple[str, str]]:
    """(file name, password) per listed backup, as the page shows them."""
    rows = re.findall(r'data-secret="([^"]+)".*?href="/admin/backups/([^"]+)"', html, re.S)
    return [(name, password) for password, name in rows]


def test_the_page_is_closed_to_someone_outside_the_team(grantee_client: TestClient) -> None:
    """A grantee sees zaken, not the maintenance page."""
    assert grantee_client.get(PAGE).status_code == 403
    assert grantee_client.post("/admin/backup").status_code == 403


def test_a_team_member_finds_the_page_in_the_menu(client: TestClient) -> None:
    """The menu bar carries Admin."""
    assert 'href="/admin"' in client.get("/zaken").text


def test_the_dropdown_lists_the_declared_mail_templates(client: TestClient) -> None:
    """The choices are the names the data dir declares under smtp.templates."""
    html = client.get(PAGE).text
    assert '<option value="intake_bevestiging">' in html


def test_a_test_mail_is_the_chosen_template_sent_to_the_given_address(
    client: TestClient, tmp_path: Path
) -> None:
    """The mail lands at the address with the template's subject and sample values."""
    outbox = use_outbox(tmp_path)
    resp = client.post(
        "/admin/testmail",
        data={"template": "intake_bevestiging", "to": "test@example.org"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    (eml,) = outbox.glob("*.eml")
    text = eml.read_text(encoding="utf8")
    assert "To: test@example.org" in text
    assert "Subject: Bevestiging van uw hulpvraag (" in text
    assert "{ref}" not in text  # every placeholder got a sample value
    assert "Verstuurd" in client.get(PAGE + "?sent=ok").text


def test_a_failed_test_mail_names_the_reason_on_the_page(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of a test mail is the reason, so the page says it rather than a bit."""
    from odas import mail

    def refuse(*args: object, **kwargs: object) -> object:
        raise mail.MailError("relay.example.nl nam het bericht niet aan.")

    monkeypatch.setattr(mail, "send", refuse)

    resp = client.post(
        "/admin/testmail",
        data={"template": "intake_bevestiging", "to": "test@example.org"},
        follow_redirects=True,
    )

    assert "Niet verstuurd" in resp.text
    assert "relay.example.nl nam het bericht niet aan." in resp.text


def test_the_page_shows_the_last_lines_of_both_logs(client: TestClient, tmp_path: Path) -> None:
    """The app log and the mail log are shown, newest line last."""
    logs = tmp_path / ".app" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "app.log").write_text("app eerste\napp laatste\n", encoding="utf8")
    (logs / "mail.log").write_text("mail eerste\nmail laatste\n", encoding="utf8")
    html = client.get(PAGE).text
    assert html.index("app eerste") < html.index("app laatste")
    assert "mail laatste" in html


def test_a_backup_opens_with_the_password_shown_beside_it(
    client: TestClient, tmp_path: Path
) -> None:
    """One click makes a zip; the page shows its password; the zip holds the zaken."""
    resp = client.post("/admin/backup", follow_redirects=False)
    assert resp.status_code == 303
    ((name, password),) = backup_rows(client.get(PAGE).text)
    assert name.endswith(".zip")
    assert len(password) >= 16
    assert f"<code>{password}</code>" not in client.get(PAGE).text  # hidden until asked for

    download = client.get(f"/admin/backups/{name}")
    assert download.headers["content-type"] == "application/zip"
    with pyzipper.AESZipFile(io.BytesIO(download.content)) as zf:
        zf.setpassword(password.encode())
        names = zf.namelist()
        index = zf.read(f"zaken/{ZAAK_FOLDER}/index.md").decode("utf8")
    assert "Mestverwerking Grubbenvorst" in index
    assert ".app/config.yaml" in names
    assert not any(n.startswith(".app/backups/") for n in names)


def test_a_backup_does_not_open_without_its_password(client: TestClient) -> None:
    """The zip is encrypted: a wrong password reads nothing."""
    client.post("/admin/backup", follow_redirects=False)
    ((name, _),) = backup_rows(client.get(PAGE).text)
    download = client.get(f"/admin/backups/{name}")
    with pyzipper.AESZipFile(io.BytesIO(download.content)) as zf:
        zf.setpassword(b"verkeerd")
        with pytest.raises(RuntimeError):
            zf.read(".app/config.yaml")


def test_backups_are_listed_newest_first(client: TestClient, tmp_path: Path) -> None:
    """The latest backup is at the top, so it is the one a person downloads."""
    backups = tmp_path / ".app" / "backups"
    backups.mkdir(parents=True)
    (backups / "20260101-000000.zip").write_bytes(b"")
    (backups / "20260101-000000.txt").write_text("oud", encoding="utf8")
    client.post("/admin/backup", follow_redirects=False)
    rows = backup_rows(client.get(PAGE).text)
    assert [r[1] for r in rows][-1] == "oud"
    assert len(rows) == 2


def test_only_a_listed_backup_can_be_downloaded(client: TestClient) -> None:
    """A name that is not a backup answers 404; it cannot reach another file."""
    assert client.get("/admin/backups/..%2Fconfig.yaml").status_code == 404
    assert client.get("/admin/backups/geen.zip").status_code == 404


def test_deleting_a_backup_removes_the_zip_and_its_password(
    client: TestClient, tmp_path: Path
) -> None:
    """After confirming, the backup is gone from the list and from disk."""
    client.post("/admin/backup", follow_redirects=False)
    ((name, _),) = backup_rows(client.get(PAGE).text)
    resp = client.post(f"/admin/backups/{name}/verwijderen", follow_redirects=False)
    assert resp.status_code == 303
    assert backup_rows(client.get(PAGE).text) == []
    assert list((tmp_path / ".app" / "backups").iterdir()) == []


def test_the_delete_button_asks_for_confirmation_first(client: TestClient) -> None:
    """The row carries a dialog that names the backup; the post is behind its confirm."""
    client.post("/admin/backup", follow_redirects=False)
    ((name, _),) = backup_rows(client.get(PAGE).text)
    html = client.get(PAGE).text
    dialog = re.search(r'<dialog id="delete-.*?</dialog>', html, re.S)
    assert dialog is not None
    assert f'action="/admin/backups/{name}/verwijderen"' in dialog.group()
    assert "Annuleren" in dialog.group()


def test_deleting_an_unknown_backup_answers_404(client: TestClient) -> None:
    """A name that is not a backup deletes nothing."""
    assert client.post("/admin/backups/geen.zip/verwijderen").status_code == 404
    assert client.post("/admin/backups/..%2Fconfig.yaml/verwijderen").status_code == 404


def test_someone_outside_the_team_cannot_delete_a_backup(grantee_client: TestClient) -> None:
    """The delete route is closed the same way as the page."""
    assert grantee_client.post("/admin/backups/x.zip/verwijderen").status_code == 403


# ---- Audit log: every zaak's trail, combined into one collapsible list. ----
# A deleted zaak keeps its line, because that is the one action no other
# page can show.


def audit_lines(html: str) -> list[str]:
    """One entry per action, in the order the page prints them."""
    found = re.search(r'<pre class="audit-log log-tail">(.*?)</pre>', html, re.S)
    return [ln for ln in found.group(1).splitlines() if ln.strip()] if found else []


def audit_refs(html: str) -> list[str]:
    """The zaak each line is about, in page order."""
    return [m.group(1) for ln in audit_lines(html) if (m := re.search(r"\b((?:zk|ds)-\d+)", ln))]


def delete_zaak(client: TestClient, ref: str) -> None:
    client.post(f"/zaken/{ref}/verwijderen", follow_redirects=False)


class Clock:
    """A minute passes between two actions, so their order is not a coin toss."""

    strptime = staticmethod(datetime.strptime)  # the reader parses with the same name

    def __init__(self) -> None:
        self.t = datetime(2026, 8, 11, 9, 0)

    def now(self) -> datetime:
        self.t += timedelta(minutes=1)
        return self.t


def test_the_audit_log_is_collapsible(client: TestClient) -> None:
    """The audit log sits behind a summary, closed until a person opens it."""
    html = client.get(PAGE).text
    section = re.search(
        r'<details class="history">\s*<summary>Audit log</summary>.*?</details>', html, re.S
    )
    assert section is not None


def test_the_newest_audit_action_is_at_the_bottom(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A case worker changes two zaken and reads the later change last, like the other logs."""
    monkeypatch.setattr("odas.audit.datetime", Clock())
    client.post(f"/zaken/{LEEG}/bewerken", data={"titel": "Eerste"}, follow_redirects=False)
    client.post(f"/zaken/{ZAAK}/bewerken", data={"titel": "Tweede"}, follow_redirects=False)

    lines = audit_lines(client.get(PAGE).text)

    assert lines.index(next(ln for ln in lines if "Eerste" in ln)) < lines.index(
        next(ln for ln in lines if "Tweede" in ln)
    )  # the later edit sits below the earlier one


def test_an_audit_line_names_when_who_which_zaak_and_what(client: TestClient) -> None:
    """Each line carries the four facts a person needs to place an action."""
    client.post(f"/zaken/{LEEG}/bewerken", data={"titel": "Nieuwe naam"}, follow_redirects=False)

    line = next(ln for ln in audit_lines(client.get(PAGE).text) if "Nieuwe naam" in ln)

    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", line)  # when
    assert LEEG in line  # which zaak
    assert TEAMLID in line  # who
    assert "Titel: Woo schutterij → Nieuwe naam" in line  # what


def test_the_audit_ref_opens_the_zaak(client: TestClient) -> None:
    """A person clicks the zaak a line is about and lands on it."""
    client.post(f"/zaken/{LEEG}/bewerken", data={"titel": "Klikbaar"}, follow_redirects=False)

    assert f'href="/zaken/{LEEG}"' in client.get(PAGE).text


def test_a_deleted_zaak_keeps_its_audit_line_and_its_actor(client: TestClient) -> None:
    """The zaak is gone, but who deleted it is still readable."""
    delete_zaak(client, LEEG)

    line = next(ln for ln in audit_lines(client.get(PAGE).text) if "verwijderd" in ln)

    assert LEEG in line
    assert TEAMLID in line


def test_a_deleted_zaak_audit_ref_is_not_a_link(client: TestClient) -> None:
    """There is nothing to open, so the page offers no way to try."""
    delete_zaak(client, LEEG)

    assert f'href="/zaken/{LEEG}"' not in client.get(PAGE).text


def test_a_dossier_audit_action_is_listed_too(client: TestClient) -> None:
    """Everything is a zaak, so a dossier's trail joins the same list."""
    ref = create_dossier(client, "Veegzaak")

    assert ref in audit_refs(client.get(PAGE).text)


def test_an_audit_log_entry_shows_up_as_its_own_action(client: TestClient) -> None:
    """Adding correspondence is a change the team should read on the page."""
    post_log(client, f"/zaken/{ZAAK}", onderwerp="Reactie gemeente")

    assert any("Reactie gemeente" in ln for ln in audit_lines(client.get(PAGE).text))


def test_an_unreadable_audit_line_does_not_hide_the_others(
    client: TestClient, tmp_path: Path
) -> None:
    """A broken audit file must never empty the page."""
    client.post(f"/zaken/{ZAAK}/bewerken", data={"titel": "Leesbaar"}, follow_redirects=False)
    trail = next(tmp_path.glob(f"zaken/{LEEG}*/audit.log"))
    trail.write_text("dit is geen regel\n", encoding="utf8")

    assert any("Leesbaar" in ln for ln in audit_lines(client.get(PAGE).text))


def test_a_trail_nobody_has_written_to_shows_an_empty_audit_log(
    client: TestClient, tmp_path: Path
) -> None:
    """With no recorded action the page says so, rather than showing a blank box."""
    for trail in tmp_path.glob("zaken/*/audit.log"):
        trail.unlink()

    assert "Nog geen activiteit." in client.get(PAGE).text


def test_a_grantee_may_not_read_the_audit_log(grantee_client: TestClient) -> None:
    """Who did what inside the team is not part of what a submitter sees."""
    assert grantee_client.get(PAGE).status_code == 403
