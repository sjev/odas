"""The overview columns: a person picks what the table shows, and a header orders it.

The config names the columns the table starts with, in the order they stand. A
person switches any list field on or off, and the browser keeps that choice. A
click on a header sorts by that column; a second click turns the order round.
"""

from __future__ import annotations

import html as htmllib
import re

from conftest import LEEG, SOLO_LEEG, SOLO_ZAAK
from fastapi.testclient import TestClient
from test_overzicht import MARK, SOLO_OTHER, chosen, header, refs_in_order, rows


def links(page: str) -> dict[str, str]:
    """Header label -> the address its link opens."""
    found = re.findall(r'<a class="sort[^"]*" href="([^"]+)">([^<]+)', header(page))
    return {label.strip(): htmllib.unescape(href) for href, label in found}


def labels(page: str) -> list[str]:
    """The column labels, left to right."""
    found = re.sub(r"<[^>]+>", "\n", header(page)).split("\n")
    return [t.strip() for t in found if t.strip() and t.strip() not in ("\u25b2", "\u25bc")]


def pick(client: TestClient, *keys: str, back: str = "/zaken") -> str:
    """Tick these boxes under Kolommen, apply, and read the page it lands on."""
    return client.post("/columns", data={"columns": list(keys), "back": back}).text


def test_the_config_names_the_columns_the_table_starts_with(client: TestClient) -> None:
    """veenwacht declares five columns; they stand in that order, after Ref, Opvolgen and Naam."""
    assert labels(client.get("/zaken").text) == [
        "Ref",
        "Opvolgen",
        "Naam",
        "Aangemaakt",
        "Gewijzigd",
        "Status",
        "Behandelaar",
        "Termijn",
    ]


def test_a_config_that_names_no_columns_shows_the_two_dates(vms_client: TestClient) -> None:
    """vms declares no column list, so the table falls back to when and when changed."""
    assert labels(vms_client.get("/zaken").text) == [
        "Ref",
        "Opvolgen",
        "Naam",
        "Aangemaakt",
        "Gewijzigd",
    ]


def test_a_click_on_a_column_header_sorts_by_that_column(client: TestClient) -> None:
    """The ref header opens the list in ref order."""
    found = refs_in_order(client.get(links(client.get("/zaken").text)["Ref"]).text)

    assert found == sorted(found)
    assert found[0] != LEEG  # the last-change order puts LEEG first


def test_a_second_click_on_the_same_header_reverses_the_order(client: TestClient) -> None:
    once = client.get(links(client.get("/zaken").text)["Ref"])
    twice = client.get(links(once.text)["Ref"]).text

    assert refs_in_order(twice) == sorted(refs_in_order(twice), reverse=True)


def test_the_sorted_column_shows_its_direction(client: TestClient) -> None:
    """A person sees which column orders the list, and which way."""
    assert "▲" in header(client.get("/zaken?sort=ref").text)
    assert "▼" in header(client.get("/zaken?sort=-ref").text)


def test_without_a_choice_the_gewijzigd_header_shows_the_order(client: TestClient) -> None:
    """The list starts in last-change order, so that header carries the arrow."""
    shown = header(pick(client, "gewijzigd"))

    assert re.search(r"Gewijzigd</a>\s*▲", shown)
    assert shown.count("▲") == 1  # the termijn header no longer claims it


def test_a_zaak_without_a_value_stays_last_in_the_reversed_order(
    solo_client: TestClient,
) -> None:
    """An empty cell is no answer, so it never rises to the top."""
    found = refs_in_order(solo_client.get("/zaken?sort=-ext_ref").text)

    assert found == [SOLO_OTHER, SOLO_ZAAK, SOLO_LEEG]  # OMG-… , 2026/… , then the empty one


def test_a_header_link_keeps_the_soort_the_status_and_the_box(client: TestClient) -> None:
    href = links(client.get("/zaken?soort=hulpvraag&status=nieuw&q=schutterij").text)["Ref"]

    assert refs_in_order(client.get(href).text) == [LEEG]
    assert "soort=hulpvraag" in href
    assert "status=nieuw" in href
    assert "sort=ref" in href


def test_a_filter_keeps_the_order_a_header_chose(client: TestClient) -> None:
    """The filter form carries the order along, so a new status keeps it."""
    assert '<input type="hidden" name="sort" value="-ref">' in client.get("/zaken?sort=-ref").text


def test_an_order_alone_offers_no_wissen(client: TestClient) -> None:
    """Wissen undoes a narrowing. An order narrows nothing, so there is nothing to undo."""
    assert "Wissen" not in client.get("/zaken?sort=-ref").text


def test_wissen_keeps_the_order(client: TestClient) -> None:
    """Wissen widens the list again; the order a header chose stays."""
    assert 'href="/zaken?sort=-ref" role="button" class="btn-cancel">Wissen' in (
        client.get("/zaken?sort=-ref&status=nieuw").text
    )


def test_the_page_draws_no_sort_dropdown(client: TestClient) -> None:
    assert '<select name="sort"' not in client.get("/zaken").text


def test_a_person_switches_on_a_field_that_is_no_default_column(
    solo_client: TestClient,
) -> None:
    """ext_instantie declares no column, but this jurist wants to read it off the list."""
    page = pick(solo_client, "ext_instantie")

    assert "Instantie" in header(page)
    assert "Provincie Limburg" in page  # SOLO_ZAAK's ext_instantie


def test_a_person_switches_off_a_default_column(solo_client: TestClient) -> None:
    page = pick(solo_client, "aangemaakt")

    assert "Kenmerk bij de instantie" not in header(page)
    assert "2026/WOO-4471" not in page  # SOLO_ZAAK's ext_ref


def test_the_column_choice_survives_the_next_page_load(solo_client: TestClient) -> None:
    """The browser keeps the choice, so a person picks it once."""
    pick(solo_client, "ext_instantie")

    assert "Instantie" in header(solo_client.get("/zaken").text)


def test_the_choice_returns_to_the_page_a_person_was_on(client: TestClient) -> None:
    page = pick(client, "gewijzigd", back="/zaken?status=nieuw&sort=ref")

    assert refs_in_order(page) == sorted(refs_in_order(page))
    assert chosen(page, "status") == "nieuw"


def test_the_choice_never_sends_a_person_to_another_site(client: TestClient) -> None:
    response = client.post(
        "/columns",
        data={"columns": ["gewijzigd"], "back": "//evil.example"},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/zaken"


def test_a_choice_that_names_no_declared_field_shows_the_defaults(
    solo_client: TestClient,
) -> None:
    """The config changes under a kept choice; the page must not break or go blank."""
    solo_client.cookies.set("columns", "weg_veld,nog_een")
    page = solo_client.get("/zaken")

    assert page.status_code == 200
    assert "Kenmerk bij de instantie" in header(page.text)


def test_a_sort_on_a_field_that_is_no_default_column_orders_by_its_value(
    solo_client: TestClient,
) -> None:
    found = refs_in_order(solo_client.get("/zaken?sort=ext_instantie").text)

    assert found == [SOLO_OTHER, SOLO_ZAAK, SOLO_LEEG]  # Gemeente…, Provincie…, then none


def test_a_click_on_the_opvolgen_header_puts_the_waiting_zaken_on_top(client: TestClient) -> None:
    """The one click that answers: what still needs the team?"""
    page = client.get(links(client.get("/zaken").text)["Opvolgen"]).text
    marked = [MARK in r for r in rows(page)]

    assert marked[0] is True
    assert marked == sorted(marked, reverse=True)  # no unmarked zaak between two marked ones


def test_a_second_click_on_the_opvolgen_header_puts_them_last(client: TestClient) -> None:
    once = client.get(links(client.get("/zaken").text)["Opvolgen"])
    marked = [MARK in r for r in rows(client.get(links(once.text)["Opvolgen"]).text)]

    assert marked[-1] is True
    assert marked == sorted(marked)


def row_href(page: str) -> str:
    """Where the first row of the table leads."""
    found = re.search(r'<a class="zaak-row" href="([^"]+)"', page)
    return htmllib.unescape(found.group(1)) if found else ""


def back_href(page: str) -> str:
    """Where the back link at the top of a zaak page leads."""
    found = re.search(r'<nav class="back-nav"><a href="([^"]+)"', page)
    return htmllib.unescape(found.group(1)) if found else ""


def test_the_back_link_of_a_zaak_returns_to_the_list_in_the_same_order(
    client: TestClient,
) -> None:
    """A person sorts, opens a zaak, and the back link brings that same order back."""
    listing = client.get(links(client.get("/zaken").text)["Ref"]).text
    zaak_page = client.get(row_href(listing)).text

    assert refs_in_order(client.get(back_href(zaak_page)).text) == refs_in_order(listing)


def test_the_back_link_also_keeps_the_search_term(client: TestClient) -> None:
    listing = client.get("/zaken?q=woo&sort=-ref").text
    zaak_page = client.get(row_href(listing)).text
    returned = client.get(back_href(zaak_page)).text

    assert refs_in_order(returned) == refs_in_order(listing)
    assert 'value="woo"' in returned  # the box still holds the term


def test_a_zaak_opened_without_a_list_behind_it_links_to_the_whole_list(
    client: TestClient,
) -> None:
    assert back_href(client.get(f"/zaken/{LEEG}").text) == "/zaken"


def test_a_back_address_on_another_host_is_refused(client: TestClient) -> None:
    """The address comes off the URL, so a mailed link must not lead off the site."""
    assert back_href(client.get(f"/zaken/{LEEG}?from=//evil.example/").text) == "/zaken"
