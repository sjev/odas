"""The summaries that are being made right now.

A job lives in memory and nowhere else. Restart the app while one runs and it is
gone: the row goes quiet again, as though nobody had pressed. That is the whole
cost of having no queue on disk, and it is the price of keeping the folder the
only record. A failure is readable until that same restart.

The pool is small on purpose. A press beyond it waits its turn rather than
opening a second bill at the provider.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from odas import ai, index

log = logging.getLogger(__name__)

BUSY = "bezig"
WORKERS = 2

_lock = threading.Lock()
_state: dict[str, str] = {}  # content hash -> BUSY, or the reason it failed
_pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="samenvatting")


def state(key: str) -> str:
    """ "" when nothing is going on, BUSY while it runs, else the failure to show."""
    with _lock:
        return _state.get(key, "")


def forget(key: str) -> None:
    """Drop what is remembered about this document, so a row can be pressed again."""
    with _lock:
        _state.pop(key, None)


def start(document: Path, key: str, by: str) -> None:
    """Ask for a summary of one document. Returns at once; the work runs behind it."""
    with _lock:
        if _state.get(key) == BUSY:
            return  # already being read; a second press is not a second bill
        _state[key] = BUSY
    _pool.submit(_run, document, key, by)


def write_one(document: Path, key: str, by: str) -> str:
    """Read the text beside it, ask the model, store what came back. Raises ValueError.

    The command line runs this in its own process; the pool below runs it here.
    """
    written = ai.summarize(index.text_of(document, key) or "", document.name)
    index.write_summary(document, key, written, by)
    return written


def _run(document: Path, key: str, by: str) -> None:
    """Do the work behind a press, and never let it reach the person who pressed."""
    try:
        write_one(document, key, by)
    except Exception as e:
        log.warning(f"Summary failed: document={str(document)!r} error={e}")
        with _lock:
            _state[key] = str(e)
        return
    forget(key)
