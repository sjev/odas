"""The store behind `odas index`.

Two things, and both lie beside the document they describe: its words in
`<naam>.tekst.md` and what was made of them in `<naam>.samenvatting.md`. They
differ in cost, not in place. Deleting every text file costs nothing but the
seconds to read the documents again; deleting a summary costs money to make
again, so nothing does.

Each records the hash of the bytes it was made from, so a replaced document reads
back as unread rather than answering with the words of the file it replaced.

Nothing outside this module builds a path into either one.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from odas import audit, naming, schema, zaak


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def digest_of(data: bytes) -> str:
    """The key a document is stored under: what is in it, never where it sits."""
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    """The same key for a file on disk, read in blocks so a bundle fits in memory."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def text_path(document: Path) -> Path:
    """Beside the document, carrying its whole name: `stuk.pdf.tekst.md`.
    The full name, not the stem, so `a.pdf` and `a.docx` never collide."""
    return document.with_name(document.name + zaak.TEXT_SUFFIX)


def _read_text(document: Path, key: str) -> tuple[dict[str, str], str] | None:
    """What lies beside this document, but only for the bytes it was read from.

    A file the parser rejects, and one that names other bytes, are both a file to
    make again rather than one to answer from.
    """
    try:
        f = text_path(document)
        if not f.is_file():
            return None
        fm, body = schema.parse(f.read_text(encoding="utf8"))
    except Exception:
        return None
    return (fm, body) if fm.get("hash") == key else None


def has_text(document: Path, key: str) -> bool:
    return _read_text(document, key) is not None


def text_of(document: Path, key: str) -> str | None:
    """The page text of these bytes. None means extraction never ran on them; an
    empty string means it ran and found no text layer."""
    found = _read_text(document, key)
    return found[1] if found else None


def pages_of(document: Path, key: str) -> int:
    """How many pages lie beside this document. Nothing read is nought pages, not
    an error."""
    found = _read_text(document, key)
    count = found[0].get("pages", "") if found else ""
    return int(count) if count.isdigit() else 0


def pages_text(document: Path, key: str) -> list[str]:
    """The text, one string per page, in the order the document holds them.
    Nothing read and no text layer both read back as no pages at all."""
    found = _read_text(document, key)
    if found is None:
        return []
    return [part.strip() for part in re.split(r"^## p\d+\n*", found[1], flags=re.M)[1:]]


def write_text(document: Path, key: str, pages: list[str]) -> None:
    """Store the text of one document beside it, one section per page.

    An empty page is kept, so the page numbers stay true. A document that yields
    no text at all is still written, with an empty body: that marks it as read, so
    a row can tell "no text layer" apart from "not read yet".
    """
    body = "\n\n".join(f"## p{i}\n\n{text}" for i, text in enumerate(pages, 1)) if pages else ""
    fm = {"document": document.name, "hash": key, "pages": len(pages), "extracted_at": _now()}
    naming.write_text_atomic(text_path(document), schema.frontmatter(fm, body))


def summary_path(document: Path) -> Path:
    """Beside the document, carrying its whole name: `stuk.pdf.samenvatting.md`.
    The full name, not the stem, so `a.pdf` and `a.docx` never collide."""
    return document.with_name(document.name + zaak.SUMMARY_SUFFIX)


def summary_of(document: Path, key: str) -> str | None:
    """The stored summary, but only for the bytes it was written from. A replaced
    document reads back None: no summary is better than the wrong one.

    A name the filesystem will not represent reads back None as well. A page only
    ever reads here, so it answers with a quiet row rather than an error page.
    """
    try:
        f = summary_path(document)
        if not f.is_file():
            return None
        fm, body = schema.parse(f.read_text(encoding="utf8"))
    except Exception:
        return None
    return body or None if fm.get("hash") == key else None


def write_summary(document: Path, key: str, text: str, by: str) -> None:
    """Store what was made of a document, whoever asked for it.

    This is a write to the zaak, so the trail records it like any other.
    """
    fm = {"document": document.name, "hash": key, "geschreven": _now()}
    try:
        naming.write_text_atomic(summary_path(document), schema.frontmatter(fm, text.strip()))
    except OSError as e:
        # The name is the document's own plus a suffix, so nothing here can shorten
        # it. Say so in words the person who pressed the button can act on.
        raise ValueError(
            f"De naam van dit bestand is te lang voor een samenvatting ({e.strerror})."
        ) from e
    audit.write(document.parents[2], f"samenvatting toegevoegd: {document.name}", by)
