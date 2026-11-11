"""Take the quoted earlier message out of a reply.

A mail client puts the message being answered under the answer. That message is
already a log entry of its own, so the copy is a second one. This module cuts it.

Only the tail is cut, and only when real words stand above the cut. What the
sender wrote themselves, sign-off included, is never touched. The message the
zaak keeps as `bericht.eml` is never touched either, so the cut is reversible.
"""

from __future__ import annotations

import re

from odas.mailin_forward import HEADER, QUOTE

MARKER = "*[eerder bericht weggelaten]*"

# `On <date> ... wrote:` and `Op <datum> ... schreef:`, however long the client
# wraps that line over.
ATTRIBUTION = re.compile(r"^\s*(on|op)\b.*\b(wrote|schreef|geschreven)\s*:?\s*$", re.I)
ANGLE = re.compile(r"^\s*>")
# A wrapper block a client writes without any marker above it.
WRAPPER_KEYS = {"from", "van", "verzonden", "sent", "aan", "to", "onderwerp", "subject"}
WRAPPER_MIN = 3  # fewer header lines than this is prose, not a wrapper
KEEP_MIN = 3  # words of the sender's own must stand above a cut
ATTRIBUTION_LINES = 3  # how far a client may wrap the line that names the quoted sender


def _wrapper_at(lines: list[str], i: int) -> bool:
    """Whether a run of header lines starts here, long enough to be a mail wrapper."""
    keys = []
    while i < len(lines) and (found := HEADER.match(lines[i])):
        keys.append(found.group(1).lower())
        i += 1
    return len(set(keys) & WRAPPER_KEYS) >= WRAPPER_MIN


def _opens_quote(lines: list[str], i: int) -> bool:
    line = lines[i]
    return bool(
        ANGLE.match(line) or QUOTE.match(line) or ATTRIBUTION.match(line) or _wrapper_at(lines, i)
    )


def _with_attribution(lines: list[str], cut: int) -> int:
    """The cut moved up over the line that names the quoted sender.

    A client wraps that line over two or three, so the last of them carries the
    `wrote:` and the ones above it carry the name. All of them belong to the quote.
    """
    for start in range(max(0, cut - ATTRIBUTION_LINES), cut):
        joined = " ".join(lines[start:cut]).strip()
        if joined and ATTRIBUTION.match(joined):
            return start
    return cut


def cut_at(body: str) -> int:
    """The line the quoted message starts on, or -1 when the body holds none."""
    lines = body.splitlines()
    for i in range(len(lines)):
        if len([x for x in lines[:i] if x.strip()]) < KEEP_MIN:
            continue
        if _opens_quote(lines, i):
            return _with_attribution(lines, i)
    return -1


def strip_quote(body: str) -> tuple[str, int]:
    """The body without the message it quotes, and how many lines that cost.

    A marker line takes the place of the cut, so a reader sees that text is gone.
    """
    cut = cut_at(body)
    if cut < 0:
        return body, 0
    removed = len(body.splitlines()) - cut
    kept = "\n".join(body.splitlines()[:cut]).rstrip()
    return f"{kept}\n\n{MARKER}", removed
