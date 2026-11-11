"""The Wetten page: the laws an organisation tracks, one box over their text.

A jurist reads the same article Claude cites, so an answer is checkable without
asking again. The law's own order is the order on screen. A hit shows the words
around the match, because that is what says whether this is the article meant.
Tests are the executable specification.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

WOO = "Wet open overheid"
VOORBEELDWET = "Voorbeeldwet"


def laws(html: str) -> list[str]:
    """The slugs the page offers, in the order a person reads them."""
    return re.findall(r'href="/wetten/([a-z]+)"', html)


def artikelen(html: str) -> list[str]:
    """The article numbers on the page, in the order they are drawn."""
    return re.findall(r'class="wet-artikel"[^>]*>\s*Artikel ([^\s<—]+)', html)


def hits(html: str) -> list[tuple[str, str]]:
    """One entry per search hit: (law slug, article stem)."""
    return re.findall(r'href="/wetten/([a-z]+)/artikel_([^"]+)"', html)


def marked(html: str) -> list[str]:
    """The words a hit marks as the match."""
    return [m.strip() for m in re.findall(r"<mark>(.*?)</mark>", html, re.S)]


def choices(html: str, name: str) -> list[str]:
    """The values a select offers."""
    found = re.search(rf'<select name="{name}".*?</select>', html, re.S)
    return re.findall(r'value="([^"]*)"', found.group(0)) if found else []


def groups(html: str) -> list[tuple[str, list[str]]]:
    """(law, its article stems) per group of hits, in the order they are drawn."""
    found = []
    for block in re.findall(r'<section class="wet-groep">(.*?)</section>', html, re.S):
        title = re.search(r"<h3.*?>(.*?)</h3>", block, re.S)
        stems = re.findall(r'href="/wetten/[a-z]+/artikel_([^"]+)"', block)
        found.append((re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else "", stems))
    return found


def nav(html: str) -> str:
    found = re.search(r"<nav.*?</nav>", html, re.S)
    return found.group(0) if found else ""


# ── The laws ──────────────────────────────────────────────────────────────────


def test_the_wetten_page_lists_every_law_the_organisation_tracks(
    vms_client: TestClient,
) -> None:
    """The page opens on the laws themselves, before any narrowing."""
    page = vms_client.get("/wetten").text

    assert sorted(laws(page)) == ["voorbeeldwet", "woo"]
    assert WOO in page
    assert VOORBEELDWET in page


def test_a_law_says_how_many_articles_it_holds_and_when_it_was_fetched(
    vms_client: TestClient,
) -> None:
    """A person reads whether a copy is old before they trust a word of it."""
    page = vms_client.get("/wetten").text

    assert "5" in page  # woo carries five articles
    assert "2026-08-15" in page  # the date its text became current


def test_an_organisation_that_tracks_no_law_says_so(client: TestClient) -> None:
    """The veenwacht example data has no wetten folder at all."""
    page = client.get("/wetten").text

    assert laws(page) == []
    assert "Nog geen wetten" in page


# ── The menu ──────────────────────────────────────────────────────────────────


def test_an_organisation_that_tracks_a_law_gets_a_wetten_entry_in_the_menu(
    vms_client: TestClient,
) -> None:
    assert '<a href="/wetten">Wetten</a>' in nav(vms_client.get("/zaken").text)


def test_an_organisation_without_law_text_has_no_wetten_entry_in_the_menu(
    client: TestClient,
) -> None:
    """The folder is the declaration, so an empty page is never offered."""
    assert "/wetten" not in nav(client.get("/zaken").text)


# ── One law ───────────────────────────────────────────────────────────────────


def test_a_law_page_shows_its_articles_in_the_order_the_law_is_written_in(
    vms_client: TestClient,
) -> None:
    """Artikel 10.1 comes last, though its filename sorts first."""
    page = vms_client.get("/wetten/woo").text

    assert artikelen(page) == ["1.1", "2.1", "2.2", "10.1", "10.2"]


def test_a_law_page_names_its_chapters(vms_client: TestClient) -> None:
    """A jurist navigates by chapter before they read any article text."""
    page = vms_client.get("/wetten/woo").text

    assert "Hoofdstuk 1. Rechten" in page
    assert "Hoofdstuk 10. Slotbepalingen" in page


def test_a_law_page_names_the_sections_inside_a_chapter(vms_client: TestClient) -> None:
    """The Awb names no article at all, so the section is what a jurist reads."""
    page = vms_client.get("/wetten/voorbeeldwet").text

    assert "Hoofdstuk 3. Bezwaar en beroep" in page
    assert "Paragraaf 3.1. Bezwaar" in page
    # A paragraaf inside an afdeling shows both, so no heading loses its words.
    assert "Afdeling 3.2. Beroep" in page
    assert "Paragraaf 3.2.1. Algemeen" in page


def test_a_law_page_lists_an_article_the_law_gave_no_name(vms_client: TestClient) -> None:
    """An article without a name is still an article a person opens."""
    page = vms_client.get("/wetten/voorbeeldwet").text

    assert artikelen(page) == ["3.1", "3.2"]
    assert '/wetten/voorbeeldwet/artikel_3-2"' in page


def test_an_unknown_law_is_not_found(vms_client: TestClient) -> None:
    assert vms_client.get("/wetten/verzonnenwet").status_code == 404


# ── One article ───────────────────────────────────────────────────────────────


def test_an_article_page_shows_its_text_with_the_date_it_became_current(
    vms_client: TestClient,
) -> None:
    """A cached article without its own date is a citation nobody can check."""
    page = vms_client.get("/wetten/woo/artikel_10-1").text

    assert "De Wet openbaarheid van bestuur wordt ingetrokken." in page
    assert "2026-08-15" in page
    assert "10. Slotbepalingen" in page


def test_an_article_page_links_back_to_the_government_copy(
    vms_client: TestClient,
) -> None:
    """Every claim on the page goes back to its source in one step."""
    page = vms_client.get("/wetten/woo/artikel_1-1").text

    assert "repository.officiele-overheidspublicaties.nl" in page
    assert 'href="/wetten/woo"' in page


def test_an_unknown_article_is_not_found(vms_client: TestClient) -> None:
    assert vms_client.get("/wetten/woo/artikel_9-9").status_code == 404


@pytest.mark.parametrize("name", ["../_wet", "..%2f_wet", "artikel_1-1/../../../etc/passwd"])
def test_an_article_path_cannot_reach_outside_the_law_folder(
    vms_client: TestClient, name: str
) -> None:
    """The URL segment names a file the folder already holds, or nothing."""
    response = vms_client.get(f"/wetten/woo/{name}")

    assert response.status_code == 404
    assert "bwb_id" not in response.text  # never the law's own _wet.md


# ── The box ───────────────────────────────────────────────────────────────────


def test_searching_for_a_word_finds_the_articles_that_carry_it(
    vms_client: TestClient,
) -> None:
    """A jurist remembers a phrase more often than a number."""
    page = vms_client.get("/wetten?q=ingetrokken").text

    assert hits(page) == [("woo", "10-1")]


def test_a_search_reads_the_article_text_and_not_only_its_title(
    vms_client: TestClient,
) -> None:
    """The words are in the body of artikel 2.2, in no title at all."""
    page = vms_client.get("/wetten?q=bestuursorganen").text

    assert ("woo", "2-2") in hits(page)


def test_a_hit_shows_the_words_around_the_match(vms_client: TestClient) -> None:
    """That is what tells a person whether this is the article they meant."""
    page = vms_client.get("/wetten?q=ingetrokken").text

    assert marked(page) == ["ingetrokken"]
    assert "De Wet openbaarheid van bestuur wordt" in page


def test_hits_from_two_laws_are_grouped_under_their_own_law(
    vms_client: TestClient,
) -> None:
    """A jurist thinks in statutes, so each law names its own hits."""
    page = vms_client.get("/wetten?q=termijn").text

    found = groups(page)
    assert [title for title, _ in found] == [VOORBEELDWET, WOO]  # by title, one order
    assert dict(found)[VOORBEELDWET] == ["3-1"]
    assert "10-2" in dict(found)[WOO]


def test_choosing_one_law_narrows_the_hits_to_it(vms_client: TestClient) -> None:
    page = vms_client.get("/wetten?q=termijn&wet=voorbeeldwet").text

    assert {slug for slug, _ in hits(page)} == {"voorbeeldwet"}


def test_the_law_choice_offers_every_tracked_law(vms_client: TestClient) -> None:
    assert sorted(choices(vms_client.get("/wetten").text, "wet")) == [
        "",
        "voorbeeldwet",
        "woo",
    ]


def test_the_box_keeps_what_a_person_typed(vms_client: TestClient) -> None:
    """A person refines a query, so the box must not empty itself."""
    assert 'value="ingetrokken"' in vms_client.get("/wetten?q=ingetrokken").text


def test_a_search_that_matches_nothing_says_so(vms_client: TestClient) -> None:
    page = vms_client.get("/wetten?q=nergensvindbaar").text

    assert hits(page) == []
    assert "Geen artikelen gevonden" in page


# ── The grammar, shared with the overview box ─────────────────────────────────


def test_quotes_hold_a_phrase_together(vms_client: TestClient) -> None:
    """Two loose words match more than the phrase does."""
    phrase = vms_client.get('/wetten?q="binnen zes weken"').text
    loose = vms_client.get("/wetten?q=binnen weken").text

    assert hits(phrase) == [("voorbeeldwet", "3-1")]
    assert hits(loose) == [("voorbeeldwet", "3-1")]
    assert hits(vms_client.get('/wetten?q="zes binnen weken"').text) == []


def test_terms_narrow_each_other(vms_client: TestClient) -> None:
    """Each term cuts the set, the way the overview box does."""
    one = vms_client.get("/wetten?q=openbaar").text
    two = vms_client.get("/wetten?q=openbaar+koninklijk").text

    assert hits(one) == [("woo", "10-1"), ("woo", "10-2")]
    assert hits(two) == [("woo", "10-2")]  # the second term cut the first one away


def test_a_wet_term_names_the_law_instead_of_searching_for_it(
    vms_client: TestClient,
) -> None:
    page = vms_client.get("/wetten?q=termijn+wet:voorbeeldwet").text

    assert {slug for slug, _ in hits(page)} == {"voorbeeldwet"}


def test_an_artikel_term_names_the_article_number(vms_client: TestClient) -> None:
    page = vms_client.get("/wetten?q=artikel:10.2").text

    assert hits(page) == [("woo", "10-2")]


def test_an_unclosed_quote_still_answers(vms_client: TestClient) -> None:
    """A person is still typing; a page must never break under a half-typed query."""
    page = vms_client.get('/wetten?q="ingetrokken').text

    assert hits(page) == [("woo", "10-1")]
