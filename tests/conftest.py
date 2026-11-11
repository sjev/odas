"""Fixtures over the example data in `tests/data/`.

Each fixture copies one profile's example data into `tmp_path`, so a test reads and
mutates real ODAS data in isolation. Example data carries its own schema in
`.app/config.yaml`, so pointing `ODAS_DATA_DIR` at it is all a test does: there
is no profile to select. Tests do not hand-write frontmatter: the example data is the
input, and the writers (`zaak_create`, `index_write`, `log_write`) are how it
changes. The exception is a test whose subject *is* parsing -- a malformed
index.md, a legacy layout -- where the literal text is the point.
"""

from __future__ import annotations

import email
import shutil
from collections.abc import Iterator
from email.message import EmailMessage
from email.policy import default as email_policy
from pathlib import Path
from typing import Any, Literal

import pytest
import yaml
from fastapi.testclient import TestClient

EXAMPLE_DATA = Path(__file__).parent / "data"

# Landmarks in the veenwacht example data. Read tests/data/veenwacht/zaken/ to see them whole.
ZAAK = "zk-00001"  # the rich one: log entries, attachments, a toegang grant, a termijn
ZAAK_FOLDER = "zk-00001-mestverwerking-grubbenvorst"
ZAAK_TITEL = "Mestverwerking Grubbenvorst"
LEEG = "zk-48595"  # created and never worked on: the empty scaffold
DOSSIER = "ds-4886"  # collects three zaken
OVERLEG = "ov-29772"  # an internal discussion: status and eigenaar, nothing else
GRANTEE = "f.wielinga@example.org"  # named in ZAAK's toegang, in no other zaak's
TEAMLID = "test@example.com"  # in the team group; the identity ODAS_TEST_MODE acts as
VEENWACHT_ZAKEN = 8

# Landmarks in the vms example data (no dossiers: its config does not declare the type).
VMS_ZAAK = "zk-21044"
VMS_ZAKEN = 3

# Landmarks in the solo example data: one jurist, `soort: procedure`, and no mail at
# all -- its `fields.log` declares only `onderwerp`.
SOLO_ZAAK = "zk-50915"  # the worked one: four log entries, a termijn, a toegang grant
SOLO_LEEG = "zk-67870"  # created and never worked on
SOLO_ZAKEN = 3

# Every config needs a `fields.log` carrying `onderwerp`, because the entry name
# is derived from it. A hand-built config has to bring one.
LOG_FIELDS: dict[str, Any] = yaml.safe_load(
    (EXAMPLE_DATA / "veenwacht" / ".app" / "config.yaml").read_text(encoding="utf8")
)["fields"]


def use_example_data(profile: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ODAS at a private copy of a profile's example data. Returns the data dir."""
    shutil.copytree(EXAMPLE_DATA / profile, tmp_path, dirs_exist_ok=True)
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))

    from odas.appconfig import get_config

    get_config.cache_clear()  # the example data carries its own schema and version
    return tmp_path


def write_config(tmp_path: Path, config: dict[str, Any] | str) -> Path:
    """Write a data dir's schema. A dict is dumped; a string is written verbatim.

    A dict gets the current `version:` unless it sets one, so a test about fields
    does not have to restate the layout revision.
    """
    from odas.dataversion import DATA_VERSION

    site = tmp_path / ".app"
    site.mkdir(parents=True, exist_ok=True)
    target = site / "config.yaml"
    if isinstance(config, dict):
        config = {"version": DATA_VERSION, **config}
    # sort_keys=False: declaration order is the field order, so it must survive.
    text = config if isinstance(config, str) else yaml.safe_dump(config, sort_keys=False)
    target.write_text(text, encoding="utf8")

    from odas.appconfig import get_config

    get_config.cache_clear()
    return target


def write_secrets(tmp_path: Path, secrets: dict[str, Any] | str) -> Path:
    """Write a data dir's secrets. A dict is dumped; a string is written verbatim."""
    site = tmp_path / ".app"
    site.mkdir(parents=True, exist_ok=True)
    target = site / "secrets.yaml"
    text = secrets if isinstance(secrets, str) else yaml.safe_dump(secrets)
    target.write_text(text, encoding="utf8")

    from odas.appsecrets import get_secrets

    get_secrets.cache_clear()
    return target


def use_outbox(tmp_path: Path) -> Path:
    """Point the active data dir's `smtp.host` at a folder. Mail lands there as .eml."""
    outbox = tmp_path / "outbox"
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["smtp"] = {**config.get("smtp", {}), "host": str(outbox)}
    write_config(tmp_path, config)
    return outbox


def use_mailin(tmp_path: Path, domain: str = "odas.example.nl") -> None:
    """Declare mail capture on the active data dir, so the zaak address exists."""
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["mailin"] = {"domains": [domain]}
    write_config(tmp_path, config)


def use_analytics(
    tmp_path: Path,
    src: str = "https://counter.example.nl/script.js",
    website_id: str = "test-website-id",
) -> None:
    """Declare a visitor counter on the active data dir, so the pages carry its tag."""
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["analytics"] = {"src": src, "website_id": website_id}
    write_config(tmp_path, config)


def fake_users(monkeypatch: pytest.MonkeyPatch, *emails: str, others: tuple[str, ...] = ()) -> None:
    """Stand in for pocket-id: these addresses are the accounts that exist.

    `emails` are in the team group, which opens every zaak. `others` are accounts
    outside it, which reach only the zaken whose `toegang:` names them.

    Every deployment has a directory, so the client fixtures install one by
    default: without it the pages that list people cannot be rendered at all.
    """
    from odas.users import User

    def person(email: str, is_team: bool) -> User:
        return User(first_name="T", last_name=email.split("@")[0], email=email, is_team=is_team)

    people = [person(e, True) for e in emails] + [person(e, False) for e in others]
    monkeypatch.setattr("odas.users.load_users", lambda: people)


class _FakeResp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc: object) -> Literal[False]:
        return False

    def get(self, path: str, params: dict[str, Any] | None = None) -> _FakeResp:
        return _FakeResp(self._payload)


def fake_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *accounts: dict[str, Any]
) -> None:
    """Stand in for the pocket-id endpoint: these are the raw account records it sends.

    `fake_users` replaces the answer; this replaces the wire, so a test can state
    what ODAS makes of the JSON a real directory hands it. The data dir must
    declare an `oidc.issuer`; the key is written here.
    """
    write_secrets(tmp_path, {"pocket_id_api_key": "k"})
    monkeypatch.setattr("odas.pocketid.httpx.Client", lambda **kw: _FakeClient({"data": accounts}))


def use_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **org: Any) -> Path:
    """An empty data dir holding the shipped template, with `org` keys overridden."""
    from odas.configload import TEMPLATE

    config = yaml.safe_load(TEMPLATE.read_text(encoding="utf8"))
    config.setdefault("org", {}).update(org)
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    write_config(tmp_path, config)
    return tmp_path


@pytest.fixture(autouse=True)
def fresh_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Config is cached for the process; each test picks its own ODAS_DATA_DIR.

    ODAS_DATA_DIR defaults to an empty temp dir carrying the shipped template, so
    a developer's real `data/` never leaks in and an unconfigured test still has
    a schema to work against.
    """
    from odas import intake_guard
    from odas.appconfig import get_config
    from odas.appsecrets import get_secrets

    intake_guard.reset()  # confirmation counts are per process
    use_config(tmp_path, monkeypatch)
    get_secrets.cache_clear()  # no data dir carries secrets unless its test writes them
    yield
    get_config.cache_clear()
    get_secrets.cache_clear()


def _client(profile: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    use_example_data(profile, tmp_path, monkeypatch)
    monkeypatch.setenv("ODAS_TEST_MODE", "1")  # auth bypassed, acting as the team
    fake_users(monkeypatch, TEAMLID, others=(GRANTEE,))

    # Imported here, after the env is set, so the app picks up this test's profile.
    from odas.app import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The veenwacht example data: intake and inzien are on, and dossiers exist."""
    yield from _client("veenwacht", tmp_path, monkeypatch)


@pytest.fixture
def vms_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The vms example data: no dossiers, no intake, a narrower field set."""
    yield from _client("vms", tmp_path, monkeypatch)


@pytest.fixture
def solo_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The solo example data: one person, no intake, no behandelaar, and no mail."""
    yield from _client("solo", tmp_path, monkeypatch)


def fake_fetch_wetten(wetten_dir: Path) -> None:
    """Stand in for `demo_seed.fetch_wetten`: no network, the same shape on disk."""
    from odas.wetten import Article, Law, write

    law = Law(
        bwb_id="BWBR0045754",
        title="Wet open overheid",
        short_title="Woo",
        valid_from="2022-05-01",
        source="fake://tests",
        articles=[Article(nr="5.2", hoofdstuk="5", secties=[], titel="", text="Voorbeeldtekst.")],
    )
    write(wetten_dir, "woo", law)


def use_demo_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ODAS at a private demo, seeded the way `odas demo init` seeds one.

    Not a profile under `tests/data/`: the seed that ships inside the package is
    what deploys, so it is what the tests read. A demo declares no directory, so
    no `fake_users` is installed here on purpose. The law text fetch is faked at
    its named seam, so tests never reach the public register.
    """
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    monkeypatch.setattr("odas.demo_seed.fetch_wetten", fake_fetch_wetten)

    from odas import cli_demo
    from odas.appconfig import get_config

    cli_demo.init()
    get_config.cache_clear()
    return tmp_path


@pytest.fixture
def demo_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A public demo: nobody signs in, and there is no user directory to ask."""
    use_demo_seed(tmp_path, monkeypatch)

    from odas.app import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def grantee_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Signed in as GRANTEE: not in the team group, named in ZAAK's toegang only."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)
    fake_users(monkeypatch, TEAMLID, others=(GRANTEE,))

    from odas.app import create_app
    from odas.auth import COOKIE_NAME, create_session_token

    with TestClient(create_app()) as c:
        c.cookies.set(COOKIE_NAME, create_session_token(GRANTEE))
        yield c


def token_of(ref: str) -> str:
    """The capability minted for an example zaak; read from disk, never hard-coded."""
    from odas import zaak

    folder = zaak.find(ref)
    assert folder is not None, ref
    return zaak.load(folder).token


def rename_field(tmp_path: Path, soort: str, old: str, new: str) -> None:
    """Give one declared field another name, keeping its declaration and its place.

    A semantic field is resolved by its kind, never by its key, so an organisation
    may call it what it likes. This is how a test states that.
    """
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    declared = config["types"][soort]
    assert old in declared, old
    config["types"][soort] = {(new if k == old else k): v for k, v in declared.items()}
    write_config(tmp_path, config)


def leave_behind(ref: str, key: str, value: str) -> Path:
    """Put a key on disk that no type declares, the way a schema change leaves one.

    The raw editor writes the whole file, so the text restates the soort the
    record already carries.
    """
    from odas import index_write, zaak

    folder = zaak.find(ref)
    assert folder is not None, ref
    z = zaak.load(folder)
    lines = [f"id: {ref}", f"soort: {z.soort}", f"{key}: {value}"]
    text = "---\n" + "\n".join(lines) + f"\n---\n\n{z.body}\n"
    index_write.update_index(folder, text, by="jev")
    return folder


def read_msg(path: Path) -> EmailMessage:
    """Parse a saved .eml file into an EmailMessage."""
    msg = email.message_from_bytes(path.read_bytes(), policy=email_policy)
    assert isinstance(msg, EmailMessage)
    return msg


def eml_files(outbox: Path) -> list[Path]:
    return sorted(outbox.glob("*.eml")) if outbox.is_dir() else []


def create_dossier(client: TestClient, titel: str = "Veegproject") -> str:
    """Create a `soort: dossier` zaak and return its ref."""
    r = client.post("/zaken", data={"titel": titel, "soort": "dossier"}, follow_redirects=False)
    return r.headers["location"].rsplit("/", 1)[-1]


def post_log(client: TestClient, base: str, **fields: str) -> Any:
    """POST a log entry under a zaak base path (e.g. '/zaken/zk-00001')."""
    data = {"direction": "LOG", "entry_date": "2026-05-20"}
    data.update(fields)
    return client.post(f"{base}/log", data=data, follow_redirects=False)
