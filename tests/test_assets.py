"""The app serves its own front end.

A jurist's office may sit behind a restrictive proxy, and which case file someone
is reading is nobody else's business. So no page may fetch a script, a stylesheet
or an image from a host other than this one: every library ODAS needs lives under
`static/vendor/` and is served from the same origin as the zaak.

Map tiles are one accepted exception, and they are named here so the exception
stays deliberate. A visitor counter is the other: it is not a library, it is
declared by the data dir rather than by this code, and the pages that carry a
token are never counted. See `test_analytics.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "odas" / "templates"
STATIC = Path(__file__).resolve().parents[1] / "src" / "odas" / "static"

# A `src=` or `href=` naming a host: absolute, or protocol-relative.
_REMOTE = re.compile(r'(?:src|href)\s*=\s*"(?:https?:)?//([^/"]+)')

# Tiles are the map. They load only when a latlon field renders, and no library
# can replace them, so this host stays.
ALLOWED_IN_SCRIPTS = {"tile.openstreetmap.org"}

# The AGPL obliges every page to offer the source. That is a link a person
# follows, never a file the page loads.
SOURCE_LINK = {"base.html -> github.com"}


def _remote_hosts(text: str) -> set[str]:
    return set(_REMOTE.findall(text))


def test_no_page_loads_anything_from_a_third_party() -> None:
    """Every asset a page needs comes from this server, so a blocked CDN cannot
    take the editor or the map away."""
    offenders = {
        f"{path.name} -> {host}"
        for path in sorted(TEMPLATES.rglob("*.html"))
        for host in _remote_hosts(path.read_text(encoding="utf8"))
    }
    assert offenders == SOURCE_LINK


def test_the_only_remote_host_the_scripts_name_is_the_tile_server() -> None:
    """The map is drawn from tiles that only a tile server has. Anything else
    appearing here is a dependency that walked back in."""
    named = {
        host
        for path in sorted(STATIC.glob("*.js"))
        for host in re.findall(r'https?://([^/"\']+)', path.read_text(encoding="utf8"))
    }
    assert named == ALLOWED_IN_SCRIPTS


@pytest.mark.parametrize(
    "path",
    [
        "/static/vendor/codemirror/codemirror.min.js",
        "/static/vendor/codemirror/codemirror.min.css",
        "/static/vendor/codemirror/yaml.js",
        "/static/vendor/leaflet/leaflet.js",
        "/static/vendor/leaflet/leaflet.css",
        # leaflet.css names these by relative path; without them the map draws
        # blank markers, which no template reference would reveal.
        "/static/vendor/leaflet/images/marker-icon.png",
        "/static/vendor/leaflet/images/marker-shadow.png",
        "/static/vendor/leaflet/images/layers.png",
    ],
)
def test_every_vendored_asset_is_actually_served(client: TestClient, path: str) -> None:
    """A reference that resolves to a 404 is worse than the CDN it replaced."""
    r = client.get(path)
    assert r.status_code == 200
    assert len(r.content) > 0


def test_the_editor_page_asks_only_for_assets_this_server_has(client: TestClient) -> None:
    """Walk what the page actually references and fetch each one, so a typo in a
    vendored path fails the build rather than the jurist's editor."""
    from conftest import ZAAK

    page = client.get(f"/zaken/{ZAAK}/bewerken")
    assert page.status_code == 200
    referenced = set(re.findall(r'(?:src|href)="(/static/[^"]+)"', page.text))
    assert referenced, "the editor page references no local assets at all"
    assert all(client.get(p).status_code == 200 for p in referenced)


def test_every_page_carries_the_theme_switch(client: TestClient) -> None:
    """The moon button and the script that drives it sit on the page itself, so a
    reader can turn the dark view on wherever they are."""
    page = client.get("/zaken")
    assert page.status_code == 200
    assert 'id="theme-toggle"' in page.text
    assert re.search(r'src="/static/theme\.js(\?v=[^"]*)?"', page.text)


def test_the_login_page_asks_only_for_assets_this_server_has(client: TestClient) -> None:
    """The login page is a second whole document, so what base.html gains it must
    gain too."""
    page = client.get("/login?error=test")
    assert page.status_code == 200
    referenced = set(re.findall(r'(?:src|href)="(/static/[^"]+)"', page.text))
    assert any(p.startswith("/static/theme.js") for p in referenced)
    assert all(client.get(p).status_code == 200 for p in referenced)


def test_a_data_dir_serves_its_own_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The logo of an org is a file in its data dir, and a stranger may load it."""
    from conftest import use_example_data

    from odas.app import create_app

    use_example_data("veenwacht", tmp_path, monkeypatch)
    monkeypatch.delenv("ODAS_TEST_MODE", raising=False)

    with TestClient(create_app()) as anon:
        r = anon.get("/assets/logo.svg", follow_redirects=False)
    assert r.status_code == 200
    assert "Veenwacht" in r.text
