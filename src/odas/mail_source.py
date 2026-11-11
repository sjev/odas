"""The stored message as a person reads it, for the window the `.eml` link opens.

The header block stands as it is on disk. That block is what a person opens a
message to check: who relayed it, who was to answer it, which identifier it
carries. The text below it is decoded, because a Dutch body travels as
quoted-printable and reads as noise. A bijlage is named and measured, never
shown: its base64 is megabytes that nobody reads, and the file is one click away.
"""

from __future__ import annotations

from odas import mailin_forward, mailin_store


def _size(count: int) -> str:
    """Dutch file size: kB below a megabyte, MB above it, with a decimal comma."""
    if count < 1024 * 1024:
        return f"{count / 1024:.0f} kB"
    return f"{count / 1024 / 1024:.1f} MB".replace(".", ",")


def _header_block(raw: bytes) -> str:
    """Everything up to the first empty line, exactly as it stands."""
    head = raw.replace(b"\r\n", b"\n").split(b"\n\n", 1)[0]
    return head.decode("utf8", "replace").strip()


def readable(raw: bytes) -> str:
    """The message as text: the headers, the body, and one line per bijlage."""
    msg = mailin_store.parse(raw)
    parts = [_header_block(raw), mailin_store.body_text(msg)]
    parts += [
        f"[bijlage: {name} — {_size(len(load))}]" for name, load in mailin_forward.files_in(msg)
    ]
    return "\n\n".join(part for part in parts if part)
