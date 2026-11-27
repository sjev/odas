"""Handlers write log entries from worker threads, so two can be made at once."""

from __future__ import annotations

import threading
import time

import pytest
from conftest import LEEG
from fastapi.testclient import TestClient

from odas import log_write, naming, zaak


def test_two_entries_made_at_once_both_stay_on_disk(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = zaak.find(LEEG)
    assert folder is not None

    def slow_letter(taken: set[str]) -> str:
        time.sleep(0.05)  # both threads look at the folder before either writes
        return naming.next_letter(taken)

    monkeypatch.setattr(log_write, "next_letter", slow_letter)
    threads = [
        threading.Thread(
            target=log_write.write_log_entry,
            args=(folder, "LOG", "notitie", f"Tekst {i}."),
            kwargs={"datum": "2026-01-15"},
        )
        for i in (1, 2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    names = sorted(p.name for p in (folder / "log").iterdir())
    assert names == ["2026-01-15-A-LOG-notitie.md", "2026-01-15-B-LOG-notitie.md"]
