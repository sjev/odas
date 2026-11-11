"""Reading the law text a data dir tracks: the laws, one law's table of contents,
one article, and the box over every article's text.

The read side of `wetten.py`, which only writes. Every answer is a folder scan on
request: a whole organisation's law text is smaller than one scanned bundle, so
no index sits between the folders and the page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from odas import schema, wetten
from odas.config import Config
from odas.zaak_query import terms

_HOOFDSTUK = re.compile(r"^## (Hoofdstuk .+)$")
_SECTIE = re.compile(r"^### (.+)$")
_ARTIKEL = re.compile(r"^- Artikel (\S+)(?: —\s*(.*))?$")  # the Awb names no article
_SLUG = re.compile(r"[\w-]+")  # a folder name, never a path
_NAME = re.compile(r"artikel_[\w.-]+")  # a file stem, never a path
_KEYS = ("wet", "artikel")  # the two terms that name a fact instead of searching
SNIPPET = 80  # characters of context on either side of a match


@dataclass
class Entry:
    """One line of a law's table of contents."""

    nr: str
    titel: str
    name: str  # the file's own name, which is what the address carries


@dataclass
class Heading:
    """One heading of a law's table of contents, with the articles under it."""

    label: str
    deep: bool  # a section inside a chapter, rather than the chapter itself
    entries: list[Entry]


@dataclass
class Hit:
    """One article the box found, with the words around the match."""

    nr: str
    titel: str
    name: str
    before: str
    match: str
    after: str


def _root() -> Path:
    return Config().wetten_dir


def _folder(slug: str) -> Path | None:
    """The law's folder, or None. A slug names a folder the root already holds."""
    if not _SLUG.fullmatch(slug):
        return None
    folder = _root() / slug
    return folder if (folder / "_wet.md").is_file() else None


def has_wetten() -> bool:
    """Whether this data dir tracks any law. The folder is the declaration, so
    this is what draws the menu entry."""
    return any(_root().glob("*/_wet.md"))


def laws() -> list[dict[str, str]]:
    """One row per tracked law, by title, each carrying how many articles it holds."""
    rows = wetten.tracked(_root())
    for row in rows:
        row["aantal"] = str(len(list((_root() / row["slug"]).glob("artikel_*.md"))))
    return sorted(rows, key=lambda r: r.get("short_title", "").casefold())


def law(slug: str) -> dict[str, str] | None:
    """One law's own metadata, or None when nothing tracks that slug."""
    return next((row for row in laws() if row["slug"] == slug), None)


def toc(slug: str) -> list[Heading]:
    """The law's headings and their articles, in the order the law is written in.

    The table of contents in `_wet.md` is that order. A folder listing is not:
    `artikel_10-1` sorts before `artikel_1-1`.
    """
    folder = _folder(slug)
    if folder is None:
        return []
    _, body = schema.parse((folder / "_wet.md").read_text(encoding="utf8"))
    headings: list[Heading] = []
    for line in body.splitlines():
        if hoofdstuk := _HOOFDSTUK.match(line):
            headings.append(Heading(hoofdstuk.group(1).strip(), False, []))
        elif sectie := _SECTIE.match(line):
            headings.append(Heading(sectie.group(1).strip(), True, []))
        elif (artikel := _ARTIKEL.match(line)) and headings:
            nr = artikel.group(1)
            titel = (artikel.group(2) or "").strip()
            headings[-1].entries.append(Entry(nr, titel, wetten.slug_artikel(nr)))
    return headings


def article(slug: str, name: str) -> tuple[dict[str, str], str] | None:
    """One article's frontmatter and text, or None.

    The address carries a file stem, so anything that is not one of this folder's
    own article files is nothing at all.
    """
    folder = _folder(slug)
    if folder is None or not _NAME.fullmatch(name):
        return None
    path = folder / f"{name}.md"
    return schema.parse(path.read_text(encoding="utf8")) if path.is_file() else None


def _body(path: Path) -> str:
    """An article's text, without parsing its frontmatter.

    The box reads every article of every law on one request, and needs none of
    those keys. Splitting instead of loading the YAML is what keeps the scan
    faster than a person notices.
    """
    text = path.read_text(encoding="utf8")
    parts = text.split("---", 2)
    return parts[2].strip() if text.startswith("---") and len(parts) == 3 else text.strip()


def _matches(term: str, row: dict[str, str], body: str) -> bool:
    """One term against one article. `wet:` and `artikel:` name a fact."""
    key, _, value = term.partition(":")
    key, value = key.casefold(), value.casefold()
    if value and key == "wet":
        return value in row["slug"].casefold() or value in row["wet"].casefold()
    if value and key == "artikel":
        return value == row["nr"].casefold()  # a number, so a near miss is a miss
    needle = term.casefold()
    return any(needle in h.casefold() for h in (row["nr"], row["titel"], row["hoofdstuk"], body))


def _needle(q: str) -> str:
    """The first term a person actually searched for, which is what a hit marks."""
    for term in terms(q):
        key, sep, _ = term.partition(":")
        if not (sep and key.casefold() in _KEYS):
            return term
    return ""


def _snippet(text: str, needle: str) -> tuple[str, str, str]:
    """The words around the first match, as three parts, so the page marks the
    middle one without ever building HTML here."""
    at = text.casefold().find(needle.casefold()) if needle else -1
    if at < 0:
        head = text[: SNIPPET * 2].strip()
        return "", "", head + (" …" if len(text) > len(head) else "")
    start, stop = max(0, at - SNIPPET), at + len(needle) + SNIPPET
    before = ("… " if start else "") + text[start:at].lstrip()
    after = text[at + len(needle) : stop].rstrip() + (" …" if stop < len(text) else "")
    return before, text[at : at + len(needle)], after


def _hits_in(row: dict[str, str], found: list[str], needle: str) -> list[Hit]:
    """One law's matching articles, in the order that law is written in."""
    folder = _root() / row["slug"]
    hits: list[Hit] = []
    for heading in toc(row["slug"]):
        for entry in heading.entries:
            path = folder / f"{entry.name}.md"
            if not path.is_file():
                continue  # the table of contents names it; the file is gone
            body = _body(path)
            fields = {
                "slug": row["slug"],
                "wet": row.get("short_title", ""),
                "nr": entry.nr,
                "titel": entry.titel,
                "hoofdstuk": heading.label,
            }
            if all(_matches(term, fields, body) for term in found):
                hits.append(Hit(entry.nr, entry.titel, entry.name, *_snippet(body, needle)))
    return hits


def search(q: str, slug: str = "") -> list[tuple[dict[str, str], list[Hit]]]:
    """The articles that carry every term, grouped by their law.

    A law with no hit is left out entirely, so the page draws no empty heading.
    """
    found, needle = terms(q), _needle(q)
    groups = [(row, _hits_in(row, found, needle)) for row in laws() if slug in ("", row["slug"])]
    return [(row, hits) for row, hits in groups if hits]
