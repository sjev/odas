"""Local law text: fetched from the government's own register (the
Basiswettenbestand) and split into one file per article.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx2 as httpx

from odas import schema

SRU_URL = "https://zoekservice.overheid.nl/sru/Search"

_NS = {
    "srw": "http://www.loc.gov/zing/srw/",
    "gzd": "http://standaarden.overheid.nl/sru",
    "bwb": "http://standaarden.overheid.nl/bwb/terms/",
    "dcterms": "http://purl.org/dc/terms/",
}


SECTIONS = ("titeldeel", "afdeling", "paragraaf", "sub-paragraaf")


@dataclass
class Article:
    nr: str
    hoofdstuk: str
    secties: list[str]  # the headings below the chapter; the Awb names nothing else
    titel: str
    text: str


@dataclass
class Law:
    bwb_id: str
    title: str
    short_title: str
    valid_from: str
    source: str
    articles: list[Article] = field(default_factory=list)


def _current_toestand(bwb_id: str) -> tuple[str, str, str]:
    """Ask the SRU search for this law; return (toestand url, title, valid_from)
    for the toestand currently in force -- the one record whose validity carries
    no end date.
    """
    # A law amended often (Awb: 236 toestanden) can outrun a small page; a law
    # this heavily amended is rare enough that one generous page is simpler
    # than paging, and cheap enough not to matter.
    params = {
        "version": "1.2",
        "operation": "searchRetrieve",
        "x-connection": "BWB",
        "query": f"dcterms.identifier=={bwb_id}",
        "maximumRecords": "500",
    }
    resp = httpx.get(SRU_URL, params=params, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    for record in root.iterfind(".//srw:record", _NS):
        meta = record.find(".//gzd:bwbipm", _NS)
        if meta is None:
            continue
        eind = meta.findtext("bwb:geldigheidsperiode_einddatum", namespaces=_NS)
        if eind != "9999-12-31":
            continue
        start = meta.findtext("bwb:geldigheidsperiode_startdatum", namespaces=_NS) or ""
        title = record.findtext(".//dcterms:title", namespaces=_NS) or ""
        url = record.findtext(".//bwb:locatie_toestand", namespaces=_NS)
        if url:
            return url, title, start
    raise LookupError(f"Geen actuele toestand gevonden voor {bwb_id}.")


def _words(el: ET.Element) -> str:
    """Every word below this element, except the bookkeeping the register hangs
    on it in <meta-data>. That is not text a person reads."""
    parts = [el.text or ""]
    for child in el:
        if child.tag != "meta-data":
            parts.append(_words(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _text(el: ET.Element | None) -> str:
    """Flatten one element to a single line of plain text; an inline reference or
    an editorial mark collapses to the words it carries."""
    return " ".join(_words(el).split()) if el is not None else ""


def _content_text(children: Iterable[ET.Element], depth: int = 0) -> str:
    """A run of paragraphs: each <al> or <tussenkop> on its own line, each
    <lijst> item on its own line below the paragraph it belongs to. What an item
    holds after its first line -- a list of its own, the words that close it --
    sits one level deeper; the page shows the text as written, indent included."""
    pad = "   " * depth
    parts = []
    for child in children:
        if child.tag in ("al", "tussenkop"):
            parts.append(pad + _text(child))
        elif child.tag == "lijst":
            for li in child.findall("li"):
                nr = li.findtext("li.nr") or "-"
                body = [c for c in li if c.tag not in ("li.nr", "meta-data")]
                head = body.pop(0) if body and body[0].tag == "al" else None
                parts.append(f"{pad}{nr} {_text(head)}".rstrip())
                parts.append(_content_text(body, depth + 1))
    return "\n".join(p for p in parts if p.strip())


def _article_text(artikel: ET.Element) -> str:
    """The article in the order it is written: each <lid> its own block, and the
    paragraphs between the lids where the law puts them. An article can hold two
    variants of itself, so a note that moves loses the lid it introduces.
    """
    blocks: list[str] = []
    run: list[ET.Element] = []
    for child in artikel:
        if child.tag != "lid":
            run.append(child)
            continue
        blocks.append(_content_text(run))
        run = []
        nr = child.findtext("lidnr") or ""
        body = _content_text(child)
        blocks.append(f"{nr}. {body}" if nr else body)
    blocks.append(_content_text(run))
    return "\n\n".join(b for b in blocks if b)


def _is_spent_amendment(artikel: ET.Element) -> bool:
    """An article whose whole body is the register's editorial line saying it
    changes another law. That change already sits in the law it changed, so this
    is legislative history, not a rule anyone can follow.
    """
    body = [child for child in artikel if child.tag not in ("kop", "meta-data")]
    if len(body) != 1 or body[0].tag != "al" or body[0].find("redactie") is None:
        return False
    return _text(body[0]).startswith("Wijzigt")  # "Vervallen" is what an article says today


def _parse_toestand(xml_text: str) -> tuple[str, list[Article]]:
    """The law's citeertitel, and its articles -- one per <artikel>, wherever it
    sits: below a <hoofdstuk>, nested in a <paragraaf>, or, in a short law like
    the Algemene termijnenwet, directly below <wettekst>."""
    root = ET.fromstring(xml_text)
    short_title = _text(root.find(".//citeertitel"))
    wettekst = root.find(".//wettekst")
    articles: list[Article] = []
    if wettekst is None:
        return short_title, articles
    _collect(wettekst, "", [], articles)
    return short_title, articles


def _heading(el: ET.Element, word: str) -> str:
    """One heading, as a person reads it: `Afdeling 2.1. Algemene bepalingen`. A
    title often ends in a reference to another law, so it is flattened like any
    other text."""
    nr = _text(el.find("kop/nr"))
    titel = _text(el.find("kop/titel"))
    return f"{word} {nr}. {titel}".strip(". ").strip()


def _collect(el: ET.Element, hoofdstuk: str, secties: list[str], articles: list[Article]) -> None:
    """Every article below one heading, each carrying the headings it sits under.
    The Awb gives no article a name, so those headings are the only wording a
    person can navigate it by.
    """
    for child in el:
        if child.tag == "hoofdstuk":
            _collect(child, _heading(child, ""), secties, articles)
        elif child.tag in SECTIONS:
            word = _text(child.find("kop/label")) or child.tag.capitalize()
            _collect(child, hoofdstuk, [*secties, _heading(child, word)], articles)
        elif child.tag == "artikel" and not _is_spent_amendment(child):
            articles.append(
                Article(
                    nr=_text(child.find("kop/nr")),
                    hoofdstuk=hoofdstuk,
                    secties=secties,
                    titel=_text(child.find("kop/titel")),
                    text=_article_text(child),
                )
            )


def fetch(bwb_id: str) -> Law:
    """The law currently in force, split into its articles."""
    url, title, valid_from = _current_toestand(bwb_id)
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    short_title, articles = _parse_toestand(resp.text)
    return Law(
        bwb_id=bwb_id,
        title=title,
        short_title=short_title or title,
        valid_from=valid_from,
        source=url,
        articles=articles,
    )


def slug_artikel(nr: str) -> str:
    """`3.3` -> `artikel_3-3`; Awb's `1:3` -> `artikel_1-3`."""
    return "artikel_" + nr.replace(".", "-").replace(":", "-")


def write(root: Path, slug: str, law: Law) -> None:
    """Write `_wet.md` and one `artikel_*.md` per article, overwriting the law's
    subfolder. Idempotent: the same toestand in always produces the same files.
    """
    folder = root / slug
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.md"):
        old.unlink()

    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    toc_lines: list[str] = []
    last_hoofdstuk: str | None = None
    last_secties: list[str] = []
    for a in law.articles:
        if a.hoofdstuk != last_hoofdstuk:
            if a.hoofdstuk:
                toc_lines.append(f"\n## Hoofdstuk {a.hoofdstuk}\n")
            last_hoofdstuk, last_secties = a.hoofdstuk, []
        for depth, sectie in enumerate(a.secties):
            if depth >= len(last_secties) or last_secties[depth] != sectie:
                toc_lines.append(f"\n### {sectie}\n")
        last_secties = a.secties
        toc_lines.append(f"- Artikel {a.nr} — {a.titel}" if a.titel else f"- Artikel {a.nr}")
    wet_fm = {
        "bwb_id": law.bwb_id,
        "title": law.title,
        "short_title": law.short_title,
        "valid_from": law.valid_from,
        "fetched_at": fetched_at,
        "source": law.source,
    }
    # A chapter whose first section follows it at once would leave two blank lines.
    toc = re.sub(r"\n{3,}", "\n\n", "\n".join(toc_lines))
    (folder / "_wet.md").write_text(schema.frontmatter(wet_fm, toc), encoding="utf8")

    for a in law.articles:
        art_fm = {
            "wet": law.title,
            "artikel": a.nr,
            **({"hoofdstuk": a.hoofdstuk} if a.hoofdstuk else {}),
            "valid_from": law.valid_from,
            "source": law.source,
        }
        path = folder / f"{slug_artikel(a.nr)}.md"
        path.write_text(schema.frontmatter(art_fm, a.text), encoding="utf8")


def add(root: Path, bwb_id: str, slug: str) -> Law:
    """Fetch a law by its BWB-ID and write it under `root/<slug>/`."""
    law = fetch(bwb_id)
    write(root, slug, law)
    return law


def update(root: Path, slug: str) -> Law:
    """Refetch a tracked law, using the `bwb_id` its own `_wet.md` already carries."""
    wet_md = root / slug / "_wet.md"
    if not wet_md.is_file():
        raise LookupError(f"Wet '{slug}' is niet gevonden in {root}.")
    from odas import schema

    fm, _ = schema.parse(wet_md.read_text(encoding="utf8"))
    return add(root, fm["bwb_id"], slug)


def tracked(root: Path) -> list[dict[str, str]]:
    """One row per tracked law: slug, plus its own `_wet.md` frontmatter."""
    from odas import schema

    if not root.is_dir():
        return []
    rows = []
    for wet_md in sorted(root.glob("*/_wet.md")):
        fm, _ = schema.parse(wet_md.read_text(encoding="utf8"))
        rows.append({"slug": wet_md.parent.name, **fm})
    return rows
