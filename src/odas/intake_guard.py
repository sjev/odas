"""Cheap defences for the public intake: bots, mail abuse, and stray file types.

The form is open to anyone, so three rules apply before a zaak is made:
a bot that fills the hidden honeypot or submits too fast is refused, only the
declared document types are stored, and one address gets a limited number of
confirmations per day, so the form cannot be used to flood someone's inbox.
"""

from __future__ import annotations

import time
from collections import defaultdict
from pathlib import PurePath

HONEYPOT = "website"
ELAPSED = "bedenktijd"  # seconds the page was open; the page's own script sets it
MIN_SECONDS = 3.0
MAILS_PER_DAY = 10
REFUSED = "Uw hulpvraag is niet verstuurd. Wacht even en probeer het opnieuw."

# A file must carry both the extension and the leading bytes of its type.
_SIGNATURES = {
    ".pdf": (b"%PDF",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".docx": (b"PK\x03\x04",),
}
ALLOWED = "pdf, jpg, png of docx"

_sent: defaultdict[str, list[float]] = defaultdict(list)


def is_bot(honeypot: str, elapsed: str) -> bool:
    """True when the hidden field holds text or the page went back too fast.

    An absent `elapsed` is not held against the sender: a browser without script
    never sets it. Only a value that is present and too small is.
    """
    if honeypot.strip():
        return True
    try:
        return bool(elapsed) and float(elapsed) < MIN_SECONDS
    except ValueError:
        return True


def bad_file(docs: list[tuple[str, bytes]]) -> str | None:
    """A Dutch message for the first document of a type not accepted; None if all pass."""
    for name, content in docs:
        signatures = _SIGNATURES.get(PurePath(name).suffix.lower(), ())
        if not any(content.startswith(s) for s in signatures):
            return f"'{name}' is geen {ALLOWED}-bestand."
    return None


def may_mail(to: str, now: float | None = None) -> bool:
    """Count a confirmation to `to`; False once the day's allowance is spent.

    Held in memory: a restart forgets the counts, which only loosens the limit.
    """
    now = time.time() if now is None else now
    key = to.strip().lower()
    recent = [t for t in _sent[key] if now - t < 86400]
    if len(recent) >= MAILS_PER_DAY:
        _sent[key] = recent
        return False
    _sent[key] = [*recent, now]
    return True


def reset() -> None:
    _sent.clear()
