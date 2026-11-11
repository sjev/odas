"""What is inside the documents of a zaak.

It reads documents and shapes the rows the page draws. Where the text and the
summaries are kept is `index.py`'s business, not this one's.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from odas import index, summary_jobs, zaak

log = logging.getLogger(__name__)

# The entry's own text and the message itself: the log line already offers both.
# The text of a document and the summary of it are not documents either.
SKIP = {"index.md", "bericht.eml"}
NO_TEXT = "geen tekstlaag"


@dataclass(frozen=True)
class Document:
    """One attachment, as the zaak page shows it."""

    name: str
    entry: str  # the log entry it arrived in, which is what the address carries
    datum: str
    key: str  # content hash: what ties its text and its summary to these bytes
    path: Path  # the document itself, and so where its summary sits
    pages: int
    summary: str
    warn: bool  # a PDF that was read and confirmed to have no text layer
    bezig: bool  # the model is reading it right now
    fout: str  # else why the last press failed, until somebody presses again


def extract(path: Path) -> list[str]:
    """The text of a PDF, one string per page. Anything else has no pages yet."""
    if path.suffix.lower() != ".pdf":
        return []
    from pypdf import PdfReader

    return [(p.extract_text() or "").strip() for p in PdfReader(str(path)).pages]


def extract_one(path: Path, force: bool = False) -> str | None:
    """Read one document and write its text beside it. Returns a warning, or None.
    `force` reads a document again even if the text beside it is already true."""
    key = index.digest(path)
    if index.has_text(path, key) and not force:
        return None
    pages = extract(path)
    if not any(pages):
        if path.suffix.lower() != ".pdf":
            return None
        index.write_text(path, key, [])
        return f"{path.name}: {NO_TEXT}"
    index.write_text(path, key, pages)
    return None


def extract_one_safe(path: Path, force: bool = False) -> tuple[Path, str | None, str | None]:
    """(path, no-text-layer warning, read error). Never raises: safe for a process pool."""
    try:
        warning = extract_one(path, force=force)
    except Exception as e:  # a document nobody can read is still a filed document
        return path, None, str(e)
    return path, warning, None


def _documents_in(entry_dir: Path) -> list[Path]:
    """The files of one log entry that are documents: not the entry's own text, not
    the message itself, and not what was read in or written about any of them."""
    return sorted(
        p
        for p in entry_dir.iterdir()
        if p.is_file() and p.name not in SKIP and not p.name.endswith(zaak.SIDECARS)
    )


def files_of(folder: Path) -> list[Path]:
    """Every document under a zaak folder, in the order extraction visits them."""
    log_dir = folder / "log"
    if not log_dir.is_dir():
        return []
    return [p for d in sorted(log_dir.iterdir()) if d.is_dir() for p in _documents_in(d)]


def _extract(paths: list[Path], on_file: Callable[[Path], None] | None, force: bool) -> list[str]:
    """Extract these documents and report what stayed unread. It never raises: a
    document nobody can read is still a filed document, so a write must not fail."""
    warnings: list[str] = []
    for path in paths:
        if on_file:
            on_file(path)
        try:
            warning = extract_one(path, force=force)
        except Exception as e:
            log.warning(f"Document could not be read: path={str(path)!r} error={e}")
            continue
        if warning:
            log.warning(f"Document has no text layer: path={str(path)!r}")
            warnings.append(warning)
    return warnings


def extract_dir(
    entry_dir: Path, on_file: Callable[[Path], None] | None = None, force: bool = False
) -> list[str]:
    """Extract the documents of one log entry, as a write does when it files them."""
    return _extract(_documents_in(entry_dir), on_file, force)


def extract_folder(
    folder: Path, on_file: Callable[[Path], None] | None = None, force: bool = False
) -> list[str]:
    """Read every document of one zaak folder that does not carry its text yet."""
    return _extract(files_of(folder), on_file, force)


def documents_of(folder: Path, z: zaak.Zaak) -> list[Document]:
    """Every attachment of the zaak as one list, whatever entry it arrived in."""
    out: list[Document] = []
    for entry in z.log_entries:
        for rel in entry.attachments:
            path = folder / rel
            if path.name in SKIP or not path.is_file():
                continue
            key = index.digest(path)
            text = index.text_of(path, key)
            job = summary_jobs.state(key)
            out.append(
                Document(
                    name=path.name,
                    entry=entry.name,
                    datum=entry.datum,
                    key=key,
                    path=path,
                    pages=index.pages_of(path, key),
                    summary=index.summary_of(path, key) or "",
                    warn=text == "" and path.suffix.lower() == ".pdf",
                    bezig=job == summary_jobs.BUSY,
                    fout="" if job == summary_jobs.BUSY else job,
                )
            )
    return out


def by_entry(docs: list[Document]) -> dict[str, list[Document]]:
    """The same documents, keyed by the log entry they arrived in."""
    out: dict[str, list[Document]] = {}
    for d in docs:
        out.setdefault(d.entry, []).append(d)
    return out
