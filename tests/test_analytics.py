"""Counting visitors is a declaration, not a build-time choice.

A data dir that declares an `analytics:` section carries the counter's tag on
every page. A data dir that declares none carries nothing at all, so one image
serves a counted demo and an uncounted organisation side by side.

The token pages are the exception. `/inzien-{token}` holds the key that opens a
zaak, and a counter records the path it loads on, so that page is never tagged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ZAAK, token_of, use_analytics
from fastapi.testclient import TestClient

WEBSITE_ID = "test-website-id"


def test_a_data_dir_that_declares_no_counter_loads_no_script(client: TestClient) -> None:
    """The example data declares no counter, so nothing is counted and no page
    reaches another host."""
    r = client.get("/zaken")
    assert r.status_code == 200
    assert "data-website-id" not in r.text


def test_a_declared_counter_is_on_every_page(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One section turns counting on. The login page is a second whole document,
    so it has to carry the tag too."""
    use_analytics(tmp_path)

    for path in ("/zaken", "/login?error=test"):
        page = client.get(path)
        assert page.status_code == 200
        assert 'src="https://counter.example.nl/script.js"' in page.text
        assert f'data-website-id="{WEBSITE_ID}"' in page.text


def test_an_inzien_page_is_never_counted(client: TestClient, tmp_path: Path) -> None:
    """The token is in the URL, so counting the page would file the key that
    opens this zaak in the counter's own database."""
    use_analytics(tmp_path)

    page = client.get(f"/inzien-{token_of(ZAAK)}")
    assert page.status_code == 200
    assert ZAAK in page.text  # the indiener still gets their zaak
    assert "data-website-id" not in page.text


def test_the_demo_ships_its_counter(demo_client: TestClient) -> None:
    """`odas demo init` writes the shipped seed, so the public demo counts
    visitors without anyone editing a file on the server."""
    page = demo_client.get("/zaken")
    assert page.status_code == 200
    assert 'src="https://m.roxautomation.com/script.js"' in page.text
    assert 'data-website-id="6bcd30f0-8bb4-4a44-b4cc-1d2e43e5ae6d"' in page.text
