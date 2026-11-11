"""The forms that hold long text keep a draft in the browser.

What the draft does is tested in `tests/js/drafts.test.cjs`. Here: each such form
asks for it, and its page loads the script that keeps it.
"""

from __future__ import annotations

import re

import pytest
from conftest import ZAAK, token_of
from fastapi.testclient import TestClient

LOG = "2026-06-06-A-LOG-zaak-heropend-na-definitief-besluit"


@pytest.mark.parametrize(
    ("page", "form"),
    [
        (f"/zaken/{ZAAK}", "log"),
        (f"/zaken/{ZAAK}/bewerken", "zaak"),
        (f"/zaken/{ZAAK}/log/{LOG}/bewerken", "log-edit"),
        ("/inzien-{token}", "reply"),
    ],
)
def test_a_form_with_long_text_keeps_a_draft_in_the_browser(
    client: TestClient, page: str, form: str
) -> None:
    """Text typed here comes back when the person leaves the page by accident."""
    html = client.get(page.format(token=token_of(ZAAK))).text
    assert re.search(rf'<form[^>]*data-draft="{form}"', html)
    assert re.search(r'src="/static/drafts\.js(\?v=[^"]*)?"', html)


def test_logging_out_removes_the_drafts_of_this_browser(client: TestClient) -> None:
    """A shared computer shows the next person nobody else's unsent text."""
    html = client.get(f"/zaken/{ZAAK}").text
    assert re.search(r'<a href="/logout"[^>]*onclick="odasDrafts\.dropAll\(\)"', html)
