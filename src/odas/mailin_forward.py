"""Read the letter out of a forwarded message.

A mail client wraps a forwarded letter in prose: a marker line, the headers of
the original, then the message. That wrapper is not correspondence, so what the
zaak files is the letter under it. An attached message needs no guessing; a
wrapper written in prose is read as far as it is readable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from odas import clock, htmltext

FORWARD = re.compile(r"^\s*-*\s*(begin\s+)?(forwarded message|doorgestuurd bericht)", re.I)
QUOTE = re.compile(r"^\s*-+\s*(original message|oorspronkelijke? bericht)\s*-*\s*$", re.I)
HEADER = re.compile(
    r"^\s*(from|van|afzender|to|aan|ontvanger|cc|kopie"
    r"|sent|verzonden|date|datum|subject|onderwerp)\s*:\s*(.*)$",
    re.I,
)
# A client breaks a long recipient line, so a line with an address continues it.
ADDRESS_KEYS = {"from", "van", "afzender", "to", "aan", "ontvanger", "cc", "kopie"}
# A client can write `<woo@gemeente.example.nl mailto:woo@gemeente.example.nl?to=...>`, no address list at all.
ADDRESS = re.compile(r"(?<!mailto:)\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
FWD_PREFIX = re.compile(r"^\s*(fwd?|doorst|doorgestuurd)\s*:\s*", re.I)
# The month names a person writes, English and Dutch, on their first three letters.
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "mrt": 3, "apr": 4, "may": 5, "mei": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "okt": 10, "nov": 11, "dec": 12,
}  # fmt: skip
MONTH = re.compile(rf"\b({'|'.join(MONTHS)})[a-z]*\b", re.I)

# More text than a covering note above the marker means a message of its own.
NOTE_LINES = 15


@dataclass(frozen=True)
class Forward:
    """The letter a forward carries. An empty field is one the wrapper never gave."""

    van: str = ""
    aan: str = ""
    cc: str = ""
    onderwerp: str = ""
    datum: str = ""
    sent: datetime | None = None  # the moment, when the wrapper states one
    message_id: str = ""
    note: str = ""
    body: str = ""
    attachments: list[tuple[str, bytes]] = field(default_factory=list)


def files_in(msg: EmailMessage) -> list[tuple[str, bytes]]:
    """Every attached part that has a name and bytes to write."""
    parts = ((p.get_filename(), p.get_payload(decode=True)) for p in msg.iter_attachments())
    return [(name, load) for name, load in parts if name and isinstance(load, bytes)]


def plain_subject(subject: str) -> str:
    """The subject of the letter, without the prefixes forwarding put in front."""
    while (stripped := FWD_PREFIX.sub("", subject, count=1)) != subject:
        subject = stripped
    return subject.strip()


def unwrap(msg: EmailMessage) -> Forward | None:
    """The letter this message forwards, or None when it forwards nothing."""
    return _attached(msg) or _inline(msg)


def _attached(msg: EmailMessage) -> Forward | None:
    """A message attached as a message: its own headers, so nothing is guessed."""
    for part in msg.walk():
        letter = part.get_payload(0) if part.get_content_type() == "message/rfc822" else None
        if not isinstance(letter, EmailMessage):
            continue
        body = letter.get_body(preferencelist=("plain", "html"))
        return Forward(
            note=_text(msg),  # what the forwarder typed
            van=_addresses(letter.get("From", "")).partition(",")[0],
            aan=_addresses(letter.get("To", "")),
            cc=_addresses(letter.get("Cc", "")),
            onderwerp=(letter["Subject"] or "").strip(),
            datum=_day(letter.get("Date", "")),
            sent=moment(letter.get("Date", "")),
            message_id=(letter["Message-ID"] or "").strip(),
            body=htmltext.part_text(body.get_content(), body.get_content_type())
            if body is not None
            else "",
            attachments=files_in(letter),
        )
    return None


def _inline(msg: EmailMessage) -> Forward | None:
    """A wrapper typed into the text. Only the topmost one opens."""
    lines = _text(msg).splitlines()
    for i, line in enumerate(lines):
        above = "\n".join(lines[:i]).strip()
        if QUOTE.match(line):  # this marker heads a reply as often as a forward
            return _read(lines, i, "") if not above else None
        if FORWARD.match(line):
            return _read(lines, i, above) if i <= NOTE_LINES else None
    return None


def _text(msg: EmailMessage) -> str:
    """The text of the message itself. Some clients send HTML alone."""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    return htmltext.part_text(part.get_content(), part.get_content_type()).strip()


def _read(lines: list[str], marker: int, note: str) -> Forward | None:
    """The header block under the marker, then everything below it."""
    i = marker + 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    values: dict[str, str] = {}
    key = ""
    while i < len(lines):
        if found := HEADER.match(lines[i]):
            key = found.group(1).lower()
            values.setdefault(key, found.group(2))
        elif key in ADDRESS_KEYS and ADDRESS.search(lines[i]):
            values[key] += " " + lines[i].strip()
        else:
            break
        i += 1
    if not values.keys() & {"from", "van", "afzender", "subject", "onderwerp"}:
        return None  # a marker with no headers under it says nothing about a letter

    def one(*keys: str) -> str:
        return next((values[k] for k in keys if k in values), "")

    return Forward(
        van=_addresses(one("from", "van", "afzender")).partition(",")[0],
        aan=_addresses(one("to", "aan", "ontvanger")),
        cc=_addresses(one("cc", "kopie")),
        onderwerp=one("subject", "onderwerp").strip(),
        datum=_day(one("sent", "verzonden", "date", "datum")),
        sent=moment(one("sent", "verzonden", "date", "datum")),
        note=note,
        body="\n".join(lines[i:]).strip(),
    )


def _addresses(value: str) -> str:
    """Every address in one wrapper line, comma-joined and without repeats."""
    return ", ".join(dict.fromkeys(found.group(0).lower() for found in ADDRESS.finditer(value)))


def moment(value: str) -> datetime | None:
    """A mail date with its zone. None when it states no time a machine can read."""
    try:
        return parsedate_to_datetime(value.strip())
    except Exception:
        return None


def _day(value: str) -> str:
    """The date a wrapper states, as JJJJ-MM-DD by the clock of the org. Empty when unreadable."""
    if at := moment(value):
        return clock.local(at).date().isoformat()
    if iso := re.search(r"\b\d{4}-\d{2}-\d{2}\b", value):
        return iso.group(0)
    month, year = MONTH.search(value), re.search(r"\b\d{4}\b", value)
    day = re.search(r"\b\d{1,2}\b", value)
    if not (month and year and day):
        return ""
    try:
        return date(int(year[0]), MONTHS[month[1].lower()], int(day[0])).isoformat()
    except ValueError:
        return ""
