"""A backup runs beside the server, so the Admin page answers at once.

Only one backup runs at a time, and a zip that is still being written is
never listed.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_admin import PAGE, backup_rows

from odas import backup


@pytest.fixture
def running_backup() -> Iterator[None]:
    """A backup that has started and not yet finished."""
    backup.RUNNING.acquire()
    yield
    backup.RUNNING.release()


def test_the_page_says_a_backup_is_being_made(client: TestClient, running_backup: None) -> None:
    """While a backup runs, the page says so and the button is off."""
    html = client.get(PAGE).text
    assert "Back-up wordt gemaakt" in html
    assert '<button type="submit" disabled>Maak back-up</button>' in html


def test_a_second_backup_does_not_start_while_one_runs(
    client: TestClient, running_backup: None
) -> None:
    """A click during a running backup adds nothing to the list."""
    resp = client.post("/admin/backup", follow_redirects=False)
    assert resp.status_code == 303
    assert backup_rows(client.get(PAGE).text) == []


def test_a_half_written_zip_is_not_listed_and_the_next_backup_clears_it(
    client: TestClient, tmp_path: Path
) -> None:
    """A crash during a backup leaves a part file; only complete zips are listed."""
    folder = tmp_path / ".app" / "backups"
    folder.mkdir(parents=True)
    (folder / "20260101-000000.zip.part").write_bytes(b"half")
    assert backup_rows(client.get(PAGE).text) == []

    client.post("/admin/backup", follow_redirects=False)
    assert len(backup_rows(client.get(PAGE).text)) == 1
    assert list(folder.glob("*.part")) == []
    assert "Back-up wordt gemaakt" not in client.get(PAGE).text  # the lock is let go
