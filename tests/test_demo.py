"""The public demonstration: one shared sandbox, no accounts, emptied every hour.

A stranger opens the demo and is already inside. They read the seeded zaken,
make one, write a logboek entry, and mail a zaak from their own client. Nothing
is prepared first, and nothing they type outlives the hour.

The demo is a declaration in the data dir, never a flag in the environment. So
every test here also states what a data dir that declares nothing still refuses.
"""

from __future__ import annotations

import shutil
from datetime import date
from email.message import EmailMessage
from pathlib import Path

import pytest
import yaml
from conftest import fake_fetch_wetten, use_demo_seed, write_config
from fastapi.testclient import TestClient

from odas import zaak

STRANGER = "willem@onbekend.example.org"
WOO = "Woo-verzoek verkeersbesluit Molenstraat"
DOSSIER = "Dossier groenbeheer Middelvoort"


def _seeded_ref(titel: str) -> str:
    """The ref the seed minted for a zaak, read off disk rather than hard-coded."""
    for z in zaak.list_all():
        if z.titel == titel:
            return z.ref
    raise AssertionError(f"Niet in de seed: {titel}")


def _message_from_a_stranger() -> bytes:
    """What a visitor's own mail client puts on the wire, with the zaak in Bcc."""
    msg = EmailMessage()
    msg["From"] = f"Willem Jansen <{STRANGER}>"
    msg["To"] = "info@middelvoort.example.nl"
    msg["Subject"] = "Aanvullende vragen bij het besluit"
    msg["Date"] = "Sat, 22 Aug 2026 11:02:00 +0200"
    msg["Message-ID"] = "<vragen-001@onbekend.example.org>"
    msg.set_content("Waarom kan een geanonimiseerde notitie niet?")
    return msg.as_bytes()


def test_a_visitor_reads_the_seeded_zaken_without_signing_in(demo_client: TestClient) -> None:
    """Open the demo and the overview is already there, with the example cases on it."""
    page = demo_client.get("/zaken").text

    assert WOO in page
    assert "Bezwaar kapvergunning Molenstraat" in page


def test_every_page_says_this_is_a_demonstration(demo_client: TestClient) -> None:
    """The warning is true on every page, so it stands on every page."""
    for address in ("/", f"/zaken/{_seeded_ref(WOO)}", "/handleiding"):
        page = demo_client.get(address).text
        assert "Demonstratie" in page, address
        assert "elk uur" in page, address


def test_a_visitor_opens_a_seeded_zaak_and_reads_its_correspondence(
    demo_client: TestClient,
) -> None:
    """The whole case is readable: the summary, and every letter that was filed."""
    page = demo_client.get(f"/zaken/{_seeded_ref(WOO)}").text

    assert "artikel 5.2" in page  # the summary in the body
    assert "Besluit gedeeltelijke openbaarmaking" in page


def test_a_document_shows_its_summary_without_any_ai_being_declared(
    demo_client: TestClient,
) -> None:
    """The seed ships its summaries, so the feature is visible and costs nothing."""
    ref = _seeded_ref(WOO)
    folder = zaak.find(ref)
    assert folder is not None
    entry = next(e for e in zaak.load(folder).log_entries if e.attachments)
    name = Path(entry.attachments[0]).name

    page = demo_client.get(f"/zaken/{ref}/log/{entry.name}/bijlage/{name}/samenvatting").text

    assert "geanonimiseerde versie" in page  # the shipped summary
    assert "samenvatten" not in page.lower()  # no ai: section, so no button


def test_a_seeded_zaak_shows_its_place_on_the_map(demo_client: TestClient) -> None:
    """The Woo-verzoek is pinned, so its page draws the map and offers the link."""
    page = demo_client.get(f"/zaken/{_seeded_ref(WOO)}").text

    assert "52.0891,5.1101" in page
    assert 'data-latlon="52.0891,5.1101"' in page  # the anchor the map dialog opens on
    assert "/static/vendor/leaflet/leaflet.js" in page


def test_the_demo_dossier_maps_both_of_its_zaken(demo_client: TestClient) -> None:
    """Both cases run on the same street, so the dossier opens one map with two pins."""
    page = demo_client.get(f"/zaken/{_seeded_ref(DOSSIER)}").text

    assert 'data-latlon="52.0891,5.1101; 52.0885,5.1123"' in page
    assert "2 locaties" in page


def test_the_seed_carries_an_internal_overleg(demo_client: TestClient) -> None:
    """The demonstration shows the internal type too: a discussion, not a case."""
    z = next(z for z in zaak.list_all() if z.soort == "overleg")

    assert z.ref.startswith("ov-")  # the prefix its type declares
    assert z.frontmatter["eigenaar"] == "ilse@demo.dasopen.nl"
    assert z.body.strip()  # a visitor reads what the overleg is about
    assert not z.token  # internal: no reply_token, so no /inzien- page


def test_the_json_write_route_stays_closed_in_a_demo(demo_client: TestClient) -> None:
    """A demo is public, and the import route is not part of what it opens."""
    answer = demo_client.post("/api/zaken", json={"titel": "Ingebroken", "soort": "procedure"})

    assert answer.status_code == 403


def test_signing_in_is_not_a_thing_in_a_demo(demo_client: TestClient) -> None:
    """There is nothing to sign in to, so the sign-in page sends you back inside."""
    answer = demo_client.get("/login", follow_redirects=False)

    assert answer.status_code == 303
    assert answer.headers["location"] == "/zaken"


def test_the_edit_page_opens_with_no_user_directory_at_all(demo_client: TestClient) -> None:
    """A demo names its own people, so the pages that list people still render."""
    page = demo_client.get(f"/zaken/{_seeded_ref(WOO)}/bewerken")

    assert page.status_code == 200
    assert "Ilse de Vries" in page.text


def test_a_visitors_edit_is_recorded_under_the_one_demo_identity(
    demo_client: TestClient,
) -> None:
    """The audit trail says a demonstration did this, never a real person's name."""
    ref = _seeded_ref(WOO)
    demo_client.post(f"/zaken/{ref}/bewerken", data={"titel": WOO, "status": "afgerond"})

    folder = zaak.find(ref)
    assert folder is not None
    trail = (folder / "audit.log").read_text(encoding="utf8")

    assert "odas-demo@dasopen.nl" in trail.splitlines()[-1]


def test_a_visitor_may_not_make_more_zaken_than_the_demo_allows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past the declared number the page refuses, and says why in Dutch."""
    use_demo_seed(tmp_path, monkeypatch)
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["demo"]["max_zaken"] = 4  # the seed already holds four
    write_config(tmp_path, config)

    from odas.app import create_app

    with TestClient(create_app()) as c:
        answer = c.post("/zaken", data={"titel": "Een vijfde zaak", "soort": "procedure"})

    assert answer.status_code == 403
    assert "demonstratie" in answer.text.lower()
    assert not any(z.titel == "Een vijfde zaak" for z in zaak.list_all())


def test_a_visitor_makes_a_zaak_while_the_demo_has_room(demo_client: TestClient) -> None:
    """Under the limit, creating works exactly as it does anywhere else."""
    demo_client.post("/zaken", data={"titel": "Zienswijze windpark", "soort": "procedure"})

    made = next(z for z in zaak.list_all() if z.titel == "Zienswijze windpark")
    assert made.frontmatter["soort"] == "procedure"


def test_a_search_engine_is_told_to_stay_out(demo_client: TestClient) -> None:
    """Whatever a stranger types here must not outlive the hour in an index."""
    answer = demo_client.get("/robots.txt")

    assert answer.status_code == 200
    assert "Disallow: /" in answer.text


def test_a_signed_message_from_a_stranger_is_filed_on_a_demo_zaak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bcc a demo zaak from your own client and the message is in the logboek."""
    use_demo_seed(tmp_path, monkeypatch)
    ref = _seeded_ref(WOO)

    from odas import mailin

    monkeypatch.setattr(mailin, "verify_dkim", lambda raw: "onbekend.example.org")
    reply = mailin.deliver(f"{ref}@odas.dasopen.nl", _message_from_a_stranger())

    assert reply.startswith("250")
    folder = zaak.find(ref)
    assert folder is not None
    entry = next(e for e in zaak.load(folder).log_entries if e.frontmatter.get("van") == STRANGER)
    assert "geanonimiseerde notitie" in entry.body


def test_a_bcc_from_a_stranger_reads_as_going_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The visitor is the caseworker here, so their Bcc files as UIT."""
    use_demo_seed(tmp_path, monkeypatch)
    ref = _seeded_ref(WOO)

    from odas import mailin

    monkeypatch.setattr(mailin, "verify_dkim", lambda raw: "onbekend.example.org")
    mailin.deliver(f"{ref}@odas.dasopen.nl", _message_from_a_stranger())

    folder = zaak.find(ref)
    assert folder is not None
    sent = next(e for e in zaak.load(folder).log_entries if e.frontmatter.get("van") == STRANGER)
    assert sent.direction == "UIT"


def test_the_generated_seed_carries_a_document_with_a_text_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A demo with no readable document shows nothing on its documents page."""
    use_demo_seed(tmp_path, monkeypatch)
    folder = zaak.find(_seeded_ref(WOO))
    assert folder is not None
    entry = next(e for e in zaak.load(folder).log_entries if e.attachments)
    document = folder / entry.attachments[0]

    from odas import index

    assert document.suffix == ".pdf"
    assert "GEMEENTE MIDDELVOORT" in (index.text_of(document, index.digest(document)) or "")
    assert "geanonimiseerde versie" in (index.summary_of(document, index.digest(document)) or "")


def test_the_seed_declares_the_layout_this_app_wants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A seed that shipped against an older layout would refuse to start."""
    use_demo_seed(tmp_path, monkeypatch)
    from odas.dataversion import DATA_VERSION

    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))

    assert config["version"] == DATA_VERSION


def test_a_reset_puts_back_a_zaak_a_visitor_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever the hour did to the zaken, the next reset has them back, whole."""
    use_demo_seed(tmp_path, monkeypatch)
    ref = _seeded_ref(WOO)
    folder = zaak.find(ref)
    assert folder is not None
    before = zaak.load(folder).frontmatter
    shutil.rmtree(folder)

    from odas import cli_demo

    cli_demo.reset()

    back = zaak.find(ref)
    assert back is not None
    after = zaak.load(back).frontmatter
    # Two fields mint fresh on every regeneration, by design: reply_token, because
    # a capability token frozen forever would be the weaker choice, and aangemaakt
    # and gewijzigd, because the reset does create these zaken now.
    for field in before.keys() - {"reply_token", "aangemaakt", "gewijzigd"}:
        assert after[field] == before[field], field


def test_a_reset_keeps_what_the_visitor_never_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The signing key survives a reset, so nobody is thrown out on the hour."""
    use_demo_seed(tmp_path, monkeypatch)
    key = tmp_path / ".app" / ".secret_key"
    key.write_text("een-sleutel-die-moet-blijven", encoding="utf8")

    from odas import cli_demo

    cli_demo.reset()

    assert key.read_text(encoding="utf8") == "een-sleutel-die-moet-blijven"


def test_a_reset_moves_the_deadline_to_a_live_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The overview always shows a deadline that is still ahead, never a stale one."""
    use_demo_seed(tmp_path, monkeypatch)
    ref = _seeded_ref(WOO)
    folder = zaak.find(ref)
    assert folder is not None
    from odas import index_write

    index_write.set_field(folder, "termijn_datum", "2019-01-01", by="demo")

    from odas import cli_demo

    cli_demo.reset()

    back = zaak.find(ref)
    assert back is not None
    due = date.fromisoformat(zaak.load(back).frontmatter["termijn_datum"])
    assert due > date.today()


def test_a_reset_asks_the_register_for_the_demo_wetten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reset against an empty volume asks the register for the law."""
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    calls: list[Path] = []
    monkeypatch.setattr("odas.demo_seed.fetch_wetten", lambda wetten_dir: calls.append(wetten_dir))

    from odas import cli_demo
    from odas.appconfig import get_config

    cli_demo.init()
    get_config.cache_clear()

    assert calls == [tmp_path / "wetten"]


def test_a_law_already_on_disk_is_not_fetched_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reset refreshes no law that is already there. It fetches only the missing one."""
    from odas import demo_seed, wetten

    fake_fetch_wetten(tmp_path)  # writes wetten/woo, nothing else
    asked: list[str] = []

    def fake_add(root: Path, bwb_id: str, slug: str) -> wetten.Law:
        asked.append(slug)
        law = wetten.Law(bwb_id, "Algemene wet bestuursrecht", "Awb", "1994-01-01", "fake://tests")
        wetten.write(root, slug, law)
        return law

    monkeypatch.setattr("odas.wetten.add", fake_add)

    demo_seed.fetch_wetten(tmp_path)

    assert asked == ["awb"]
    assert "fake://tests" in (tmp_path / "woo" / "_wet.md").read_text()  # the Woo write of the seed
    assert "Algemene wet bestuursrecht" in (tmp_path / "awb" / "_wet.md").read_text()


def test_a_data_dir_that_declares_no_demo_still_asks_who_you_are(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The demo is a declaration in one file. Nothing about it reaches a live org."""
    from odas.appconfig import demo

    assert demo() is None


def test_a_notice_the_demo_sends_lands_in_one_outbox_beside_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The demo relays to disk, so its outbox sits in `.app/`, not a level deeper."""
    use_demo_seed(tmp_path, monkeypatch)
    from odas import mail_transport

    msg = EmailMessage()
    msg["Subject"] = "Uw zaak is aangemaakt"
    msg.set_content("U ziet uw zaak in via de link.")
    mail_transport.deliver(msg, [STRANGER])

    written = list((tmp_path / ".app" / "uitgaand").glob("*.eml"))
    assert [p.read_text(encoding="utf8").count("Uw zaak is aangemaakt") for p in written] == [1]
    assert not (tmp_path / ".app" / ".app").exists()  # the old doubled path is gone


def test_a_demonstration_has_no_admin_page(demo_client: TestClient) -> None:
    """A visitor is no administrator: the logs hold other visitors' addresses."""
    for path in ("/admin", "/log", "/log/mail"):
        r = demo_client.get(path)
        assert r.status_code == 404, path
        assert "Maak back-up" not in r.text


def test_a_demonstration_shows_no_admin_link(demo_client: TestClient) -> None:
    """The menu offers no page that answers 404."""
    assert 'href="/admin"' not in demo_client.get("/zaken").text
