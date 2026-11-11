"""The overview page: three choices, one box, one table row per zaak.

A person matches a page against a ref they read in an email, so the row carries
the ref and the deadline. The table names its columns once, and every row lines
up under them whatever soort it is. Nothing on this page is behind a hover. The
Tests are the executable specification.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from conftest import (
    DOSSIER,
    LEEG,
    OVERLEG,
    SOLO_LEEG,
    SOLO_ZAAK,
    VMS_ZAAK,
    ZAAK,
    ZAAK_TITEL,
    write_config,
)
from fastapi.testclient import TestClient

from odas import index_write, zaak, zaak_create

SOLO_OTHER = "zk-48426"  # the solo zaak whose ext_ref starts with a letter
MARK = 'class="zaak-flag"'  # the flag the Opvolgen column draws


def rows(html: str) -> list[str]:
    """One entry per zaak row: what a person reads off the table."""
    return re.findall(r'<a class="zaak-row".*?</a>', html, re.S)


def header(html: str) -> str:
    """The row that names the columns."""
    found = re.search(r'<div class="zaak-header".*?</div>', html, re.S)
    return found.group(0) if found else ""


def cell_count(row: str) -> int:
    return len(re.findall(r'<span class="zaak-cell"', row))


def row_of(html: str, ref: str) -> str:
    """The one row of that zaak."""
    return next(r for r in rows(html) if ref in r)


def refs_in_order(html: str) -> list[str]:
    return re.findall(r'<span class="zaak-ref">([^<]+)</span>', html)


def _choice(html: str, name: str) -> str:
    """The named dropdown inside the filter form, or "" when the page draws none.

    Scoped to that form: the dialog that creates a zaak also carries a `soort`.
    """
    form = re.search(r'<form class="zoek".*?</form>', html, re.S)
    found = re.search(rf'<select name="{name}".*?</select>', form.group(0), re.S) if form else None
    return found.group(0) if found else ""


def choices(html: str, name: str) -> list[str]:
    """The values a person may pick from the named dropdown."""
    return re.findall(r'<option value="([^"]*)"', _choice(html, name))


def chosen(html: str, name: str) -> str:
    """The value the named dropdown shows as picked."""
    found = re.search(r'<option value="([^"]*)"[^>]*\bselected\b', _choice(html, name))
    return found.group(1) if found else ""


# ── The row ───────────────────────────────────────────────────────────────────


def test_the_overview_row_shows_the_ref_and_the_deadline_without_hovering(
    client: TestClient,
) -> None:
    """The ref is the identity in an email, so a person reads it off the row itself."""
    listed = "\n".join(rows(client.get("/zaken").text))

    assert ZAAK in listed
    assert ZAAK_TITEL in listed
    assert "2026.06.26" in listed  # ZAAK's termijn_datum, through the `dt` filter


def test_the_whole_row_opens_the_zaak(client: TestClient) -> None:
    """One row, one destination: there is nothing to open the row itself for."""
    found = [r for r in rows(client.get("/zaken").text) if ZAAK_TITEL in r]

    assert len(found) == 1
    assert f'href="/zaken/{ZAAK}?from=' in found[0]  # the zaak, and the list to return to


def test_no_page_hides_a_fact_behind_a_hover(client: TestClient) -> None:
    """A tooltip has no touch target, so the row opens instead."""
    page = client.get("/zaken").text

    assert "zaak-tip" not in page
    assert "zaak-tip" not in client.get(f"/zaken/{DOSSIER}").text  # the members list too


def test_the_row_shows_the_date_of_intake(client: TestClient) -> None:
    """Every zaak carries the date it was made, so the table names it for every soort."""
    page = client.get("/zaken").text
    listed = next(r for r in rows(page) if ZAAK in r)

    assert "Aangemaakt" in header(page)
    assert "2026.02.10" in listed  # ZAAK's aangemaakt, through the `dt` filter


def test_a_field_marked_column_shows_in_the_table(solo_client: TestClient) -> None:
    """solo declares `column: true` on ext_ref: its kenmerk is what it looks a zaak up by."""
    listed = "\n".join(rows(solo_client.get("/zaken").text))

    assert "2026/WOO-4471" in listed  # SOLO_ZAAK's ext_ref


def test_a_field_without_column_stays_off_the_table(solo_client: TestClient) -> None:
    """ext_instantie declares no column, so it is read on the zaak page instead."""
    page = solo_client.get("/zaken").text

    assert "Provincie Limburg" not in page
    assert "Provincie Limburg" in solo_client.get(f"/zaken/{SOLO_ZAAK}").text


def test_the_table_names_its_columns(solo_client: TestClient) -> None:
    """A value with no label is a riddle, so the header carries the declared label."""
    assert "Kenmerk bij de instantie" in header(solo_client.get("/zaken").text)


def test_a_soort_without_a_column_field_still_lines_up(client: TestClient) -> None:
    """dossier declares no status, so its row leaves that cell empty rather than shifting."""
    listed = rows(client.get("/zaken").text)
    hulpvraag = next(r for r in listed if ZAAK in r)
    dossier = next(r for r in listed if DOSSIER in r)

    assert cell_count(dossier) == cell_count(hulpvraag)  # one header, one set of positions


def test_a_zaak_that_cannot_be_read_still_gets_a_row(client: TestClient, tmp_path: Path) -> None:
    """A broken file must never make a zaak disappear from the list."""
    index = tmp_path / "zaken" / "zk-48595-woo-schutterij" / "index.md"
    index.write_text("---\ntitel: [unclosed\n---\n", encoding="utf8")

    page = client.get("/zaken").text
    assert LEEG in page
    assert "kan niet worden gelezen" in page


# ── The soort choice ──────────────────────────────────────────────────────────


def test_picking_a_soort_narrows_the_list_to_that_type(client: TestClient) -> None:
    """A dossier choice holds dossiers and nothing else."""
    dossiers = refs_in_order(client.get("/zaken?soort=dossier").text)
    assert DOSSIER in dossiers
    assert ZAAK not in dossiers

    hulpvragen = refs_in_order(client.get("/zaken?soort=hulpvraag").text)
    assert ZAAK in hulpvragen
    assert DOSSIER not in hulpvragen


def test_the_soort_choice_offers_every_declared_type(client: TestClient) -> None:
    """The empty value is "Alle": no soort chosen, every soort listed."""
    assert choices(client.get("/zaken").text, "soort") == ["", "hulpvraag", "dossier", "overleg"]


def test_the_soort_choice_says_how_many_zaken_sit_behind_each_type(client: TestClient) -> None:
    """A person reads the size of a set before they open it."""
    page = _choice(client.get("/zaken").text, "soort")

    assert "Hulpvraag (5)" in page
    assert "Dossier (2)" in page


def test_the_page_remembers_which_soort_a_person_picked(client: TestClient) -> None:
    assert chosen(client.get("/zaken?soort=dossier").text, "soort") == "dossier"


def test_a_data_dir_with_one_type_offers_no_choice(vms_client: TestClient) -> None:
    """vms declares only `procedure`, so there is nothing to choose between."""
    page = vms_client.get("/zaken").text

    assert VMS_ZAAK in refs_in_order(page)
    assert choices(page, "soort") == []


def test_a_zaak_of_an_undeclared_soort_is_still_offered(client: TestClient, tmp_path: Path) -> None:
    """Data outlives the schema that made it: a retired type must not hide its zaken."""
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    del config["types"]["hulpvraag"]  # the org retires a type; its zaken stay on disk
    write_config(tmp_path, config)

    assert "overig" in choices(client.get("/zaken").text, "soort")
    overig = refs_in_order(client.get("/zaken?soort=overig").text)
    assert ZAAK in overig
    assert DOSSIER not in overig  # dossier is still declared, so it keeps its own entry


def test_the_soort_choice_stays_offered_when_a_status_narrows_it_to_one_type(
    client: TestClient,
) -> None:
    """Which soort is on offer is a fact about the data dir, not about the current filter.

    dossier declares no status field, so a status pick always narrows it to zero
    and drops it from the list. The choice itself must still be drawn.
    """
    page = client.get("/zaken?status=nieuw").text
    assert _choice(page, "soort") != ""
    assert "" in choices(page, "soort")  # "Alle" is still on offer


# ── The status choice ─────────────────────────────────────────────────────────


def test_picking_a_status_narrows_the_list_to_that_status(client: TestClient) -> None:
    """The common narrowing costs no typing: it is the same set as `status:nieuw`."""
    found = refs_in_order(client.get("/zaken?status=nieuw").text)

    assert LEEG in found  # created and never worked on
    assert ZAAK not in found  # in_behandeling


def test_the_status_choice_offers_the_values_the_organisation_declared(
    vms_client: TestClient,
) -> None:
    """vms declares three values, not the four generic ones: this team never waits."""
    assert choices(vms_client.get("/zaken").text, "status") == [
        "",
        "nieuw",
        "in_behandeling",
        "afgerond",
    ]


def test_the_page_remembers_which_status_a_person_picked(client: TestClient) -> None:
    assert chosen(client.get("/zaken?status=afgerond").text, "status") == "afgerond"


def test_a_data_dir_without_a_status_field_offers_no_status_choice(
    client: TestClient, tmp_path: Path
) -> None:
    """A field nobody declares is a choice nobody is offered."""
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    del config["types"]["hulpvraag"]["status"]
    del config["types"]["overleg"]["status"]
    write_config(tmp_path, config)

    assert choices(client.get("/zaken").text, "status") == []


# ── The filter box ────────────────────────────────────────────────────────────


def test_filtering_on_a_ref_returns_that_one_zaak(client: TestClient) -> None:
    """The known item: a person types the ref they read in an email."""
    found = refs_in_order(client.get(f"/zaken?q={ZAAK}").text)

    assert found == [ZAAK]


def test_filtering_on_a_word_from_the_title_returns_that_zaak(client: TestClient) -> None:
    assert refs_in_order(client.get("/zaken?q=euromast").text) == ["zk-93810"]


def test_a_word_from_any_field_finds_the_zaak(client: TestClient) -> None:
    """A person types the contact's name, not the key it is stored under."""
    assert refs_in_order(client.get("/zaken?q=broekhuizen").text) == ["zk-42817"]  # contact_naam


def test_a_word_matches_whatever_its_case(client: TestClient) -> None:
    assert refs_in_order(client.get("/zaken?q=BROEKHUIZEN").text) == ["zk-42817"]
    assert refs_in_order(client.get("/zaken?q=EuroMast").text) == ["zk-93810"]


def test_filtering_on_soort_returns_only_that_type(client: TestClient) -> None:
    """Every declared field is a facet, because the term names the key on disk."""
    found = refs_in_order(client.get("/zaken?q=soort:dossier").text)

    assert DOSSIER in found
    assert ZAAK not in found


def test_filtering_on_status_returns_only_that_status(client: TestClient) -> None:
    found = refs_in_order(client.get("/zaken?q=status:nieuw").text)

    assert LEEG in found  # created and never worked on
    assert ZAAK not in found  # in_behandeling


def test_filtering_on_a_month_returns_the_zaken_of_that_month(client: TestClient) -> None:
    """The month overview: a part of the date narrows the list to one month."""
    found = refs_in_order(client.get("/zaken?q=aangemaakt:2026-07").text)

    assert set(found) == {DOSSIER, "ds-9308", LEEG, OVERLEG}  # the four made in July 2026
    assert ZAAK not in found  # made in February


def test_a_space_after_the_colon_still_names_the_field(client: TestClient) -> None:
    """`status: nieuw` reads as one term: the space a person types by habit is forgiven."""
    assert refs_in_order(client.get("/zaken?q=status:+nieuw").text) == refs_in_order(
        client.get("/zaken?q=status:nieuw").text
    )
    assert LEEG in refs_in_order(client.get("/zaken?q=aangemaakt:+2026-07").text)


def test_two_terms_both_have_to_match(client: TestClient) -> None:
    assert refs_in_order(client.get("/zaken?q=soort:hulpvraag+schutterij").text) == [LEEG]


def test_a_quoted_phrase_matches_only_where_the_words_sit_together(
    solo_client: TestClient,
) -> None:
    """Quotes hold a phrase together; without them the words may sit anywhere."""
    together = refs_in_order(solo_client.get('/zaken?q="stikstofvergunningen peelregio"').text)
    assert together == [SOLO_ZAAK]

    apart = refs_in_order(solo_client.get('/zaken?q="woo-verzoek peelregio"').text)
    assert apart == []  # both words are in the title, but not next to each other


def test_a_filter_that_matches_nothing_says_so(client: TestClient) -> None:
    page = client.get("/zaken?q=nergensvindbaar").text

    assert refs_in_order(page) == []
    assert "Geen zaken gevonden" in page


def test_the_box_keeps_what_a_person_typed(client: TestClient) -> None:
    """A person refines a query, so the box must not empty itself on every request."""
    assert 'value="euromast"' in client.get("/zaken?q=euromast").text


def test_a_grantee_never_sees_a_zaak_they_may_not_open(grantee_client: TestClient) -> None:
    """Access comes before narrowing: a filter can never widen what a person sees."""
    assert refs_in_order(grantee_client.get("/zaken?q=soort:hulpvraag").text) == [ZAAK]


# ── Order ─────────────────────────────────────────────────────────────────────


def test_the_most_recently_changed_zaak_comes_first(client: TestClient) -> None:
    """Without a choice, a note on the oldest zaak brings it to the top of the list."""
    client.post(
        "/zaken/zk-42817/log",
        data={"direction": "LOG", "onderwerp": "telefoon", "body": "Gebeld over de stand."},
    )

    assert (
        refs_in_order(client.get("/zaken").text)[0] == "zk-42817"
    )  # 2026-01-13, the oldest by intake


def test_sorting_by_ref_overrides_the_default_order(client: TestClient) -> None:
    found = refs_in_order(client.get("/zaken?sort=ref").text)

    assert found == sorted(found)
    assert found[0] != LEEG  # the last-change order puts LEEG first; the ref order does not


def test_sorting_by_the_date_of_intake_puts_the_newest_zaak_first(client: TestClient) -> None:
    """A person asks what came in last, so the newest zaak stands at the top."""
    found = refs_in_order(client.get("/zaken?sort=aangemaakt").text)

    assert found[0] == LEEG  # 2026-07-25 14:33, the newest of the veenwacht zaken
    assert found[-1] == "zk-42817"  # 2026-01-13, the oldest


def test_a_zaak_without_a_date_of_intake_comes_last(client: TestClient) -> None:
    """A missing stamp must never look like the newest zaak of all."""
    made = zaak_create.create_minimal("Zonder stempel", "hulpvraag")
    folder = zaak.find(made.ref)
    assert folder is not None
    index_write.set_field(folder, "aangemaakt", "", "teamlid")

    found = refs_in_order(client.get("/zaken?sort=aangemaakt").text)

    assert found[-1] == made.ref


def test_sorting_by_last_change_puts_the_most_recently_changed_zaak_first(
    client: TestClient,
) -> None:
    """A note on the oldest zaak brings it to the top: that is where the work is."""
    client.post(
        "/zaken/zk-42817/log",
        data={"direction": "LOG", "onderwerp": "telefoon", "body": "Gebeld over de stand."},
    )

    found = refs_in_order(client.get("/zaken?sort=gewijzigd").text)

    assert found[0] == "zk-42817"  # 2026-01-13, the oldest by intake


def test_sorting_by_a_column_field_orders_by_its_value(solo_client: TestClient) -> None:
    """A zaak without a value for that field comes last, not first."""
    found = refs_in_order(solo_client.get("/zaken?sort=ext_ref").text)

    assert found == [SOLO_ZAAK, SOLO_OTHER, SOLO_LEEG]  # 2026/… , OMG-… , then the empty one


def test_sorting_by_status_follows_the_declared_order(client: TestClient) -> None:
    """A workflow runs nieuw, in behandeling, wacht, afgerond: not the alphabet."""
    found = refs_in_order(client.get("/zaken?sort=status").text)

    assert found[0] == LEEG  # nieuw
    assert found.index("zk-93810") < found.index(DOSSIER)  # afgerond, then the statusless


def test_the_page_keeps_every_choice_a_person_made(client: TestClient) -> None:
    """Three narrowings and an order combine, and the page comes back stating all four."""
    page = client.get("/zaken?soort=hulpvraag&status=nieuw&sort=titel&q=schutterij").text

    assert refs_in_order(page) == [LEEG]
    assert chosen(page, "soort") == "hulpvraag"
    assert chosen(page, "status") == "nieuw"
    assert '<input type="hidden" name="sort" value="titel">' in page
    assert 'value="schutterij"' in page


@pytest.mark.parametrize("sort", ["titel", "status", "onzin"])
def test_a_hand_typed_sort_never_produces_an_error_page(client: TestClient, sort: str) -> None:
    """A hand-typed address must never produce an error page."""
    assert client.get(f"/zaken?sort={sort}").status_code == 200


def test_an_unknown_sort_falls_back_to_the_last_change_order(client: TestClient) -> None:
    assert refs_in_order(client.get("/zaken?sort=onzin").text) == refs_in_order(
        client.get("/zaken").text
    )


def test_an_unknown_status_shows_an_empty_list_and_no_error(client: TestClient) -> None:
    page = client.get("/zaken?status=onzin")

    assert page.status_code == 200
    assert refs_in_order(page.text) == []
