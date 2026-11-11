"""Fetching a law from the government's register and reading it back per article."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from odas import schema, wetten
from odas.cli import app

FIXTURES = Path(__file__).parent / "data" / "wetten_fixtures"
SRU_RESPONSE = (FIXTURES / "sru_response.xml").read_text(encoding="utf8")
SRU_RESPONSE_NO_CURRENT = (FIXTURES / "sru_response_no_current.xml").read_text(encoding="utf8")
WOO_TOESTAND = (FIXTURES / "woo_toestand.xml").read_text(encoding="utf8")
PARAGRAAF_TOESTAND = (FIXTURES / "paragraaf_toestand.xml").read_text(encoding="utf8")
NESTED_LIST_TOESTAND = (FIXTURES / "nested_list_toestand.xml").read_text(encoding="utf8")
TOESTAND_URL = (
    "https://repository.officiele-overheidspublicaties.nl/bwb/BWBR0045754/"
    "2026-08-15_0/xml/BWBR0045754_2026-08-15_0.xml"
)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


def _fake_get(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = {wetten.SRU_URL: SRU_RESPONSE, TOESTAND_URL: WOO_TOESTAND}

    def get(url: str, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(responses[url])

    monkeypatch.setattr("odas.wetten.httpx.get", get)


def test_fetching_a_law_writes_its_table_of_contents_and_one_article(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_get(monkeypatch)

    wetten.add(tmp_path, "BWBR0045754", "woo")

    wet_fm, wet_body = schema.parse((tmp_path / "woo" / "_wet.md").read_text(encoding="utf8"))
    assert wet_fm["bwb_id"] == "BWBR0045754"
    assert wet_fm["title"] == "Wet open overheid"
    assert wet_fm["short_title"] == "Wet open overheid"
    assert wet_fm["valid_from"] == "2026-08-15"
    assert wet_fm["source"] == TOESTAND_URL
    assert "Artikel 1.1 — Recht op toegang" in wet_body

    art_fm, art_body = schema.parse(
        (tmp_path / "woo" / "artikel_1-1.md").read_text(encoding="utf8")
    )
    assert art_fm["wet"] == "Wet open overheid"
    assert art_fm["artikel"] == "1.1"
    assert art_fm["valid_from"] == "2026-08-15"
    assert art_fm["source"] == TOESTAND_URL
    assert art_body == (
        "Eenieder heeft recht op toegang tot publieke informatie zonder daartoe "
        "een belang te hoeven stellen, behoudens bij deze wet gestelde beperkingen."
    )


def test_an_article_with_lid_numbers_each_lid_and_its_own_lettered_list() -> None:
    _, articles = wetten._parse_toestand(WOO_TOESTAND)

    reikwijdte = next(a for a in articles if a.nr == "2.2")

    assert reikwijdte.hoofdstuk == "2. Algemene bepalingen"
    assert reikwijdte.text.startswith("1. Deze wet is van toepassing op:\na. bestuursorganen;")
    assert "\n\n2. Voor de toepassing van deze wet" in reikwijdte.text


def test_an_article_without_lid_renders_its_unmarked_list_with_dashes() -> None:
    _, articles = wetten._parse_toestand(WOO_TOESTAND)

    begripsbepalingen = next(a for a in articles if a.nr == "2.1")

    assert begripsbepalingen.text.startswith(
        "In deze wet en de daarop berustende bepalingen wordt verstaan onder:\n"
        "- document: een door een orgaan, persoon of college"
    )


def test_a_list_inside_a_list_item_keeps_its_items_indented_below_it() -> None:
    """A jurist reads the cases of Omgevingswet 16.15a onder b, not only the
    line that announces them."""
    _, articles = wetten._parse_toestand(NESTED_LIST_TOESTAND)

    assert articles[0].text == (
        "Op grond van artikel 16.15, eerste lid, worden in ieder geval als adviseur aangewezen:\n"
        "a. een bestuursorgaan dat zijn bevoegdheid heeft overgedragen,\n"
        "b. de gemeenteraad als het gaat om:\n"
        "   1°. een aanvraag om een omgevingsvergunning voor in door de gemeenteraad"
        " aangewezen gevallen van een buitenplanse omgevingsplanactiviteit,\n"
        "   2°. een verzoek om een beslissing over instemming,\n"
        "c. gedeputeerde staten in door hen aangewezen gevallen."
    )


def test_a_nested_list_inside_a_lid_keeps_the_lid_number_on_its_first_line_only() -> None:
    _, articles = wetten._parse_toestand(NESTED_LIST_TOESTAND)

    artikel = next(a for a in articles if a.nr == "16.7")

    assert artikel.text.startswith(
        "1. Gecoördineerd worden voorbereid:\n"
        "a. de beslissingen op aanvragen voor:\n"
        "   1°. een of meer wateractiviteiten, en\n"
    )


def test_the_words_after_a_nested_list_stay_with_the_item_they_close() -> None:
    _, articles = wetten._parse_toestand(NESTED_LIST_TOESTAND)

    artikel = next(a for a in articles if a.nr == "16.7")

    assert artikel.text.endswith(
        "   2°. een of meer andere activiteiten,\n   die gelijktijdig zijn ingediend,"
    )


def test_an_unnumbered_item_with_a_list_of_its_own_nests_three_levels_deep() -> None:
    _, articles = wetten._parse_toestand(NESTED_LIST_TOESTAND)

    artikel = next(a for a in articles if a.nr == "2.18")

    assert artikel.text == (
        "De provincie heeft tot taak:\n"
        "- natuur:\n"
        "   1°. maatregelen voor:\n"
        "      i. Natura 2000-gebieden."
    )


def test_an_article_title_keeps_the_law_that_its_reference_names() -> None:
    _, articles = wetten._parse_toestand(WOO_TOESTAND)

    intrekking = next(a for a in articles if a.nr == "10.1")

    assert intrekking.titel == "Intrekking Wet openbaarheid van bestuur"  # ends in an <extref>


def test_an_article_that_only_changes_another_law_is_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_get(monkeypatch)

    wetten.add(tmp_path, "BWBR0045754", "woo")

    _, wet_body = schema.parse((tmp_path / "woo" / "_wet.md").read_text(encoding="utf8"))
    assert "9.47" not in wet_body  # it says only "Wijzigt de Woningwet."
    assert not (tmp_path / "woo" / "artikel_9-47.md").exists()


def test_a_chapter_that_only_changes_other_laws_leaves_no_heading_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_get(monkeypatch)

    wetten.add(tmp_path, "BWBR0045754", "woo")

    _, wet_body = schema.parse((tmp_path / "woo" / "_wet.md").read_text(encoding="utf8"))
    assert "Hoofdstuk 9" not in wet_body
    assert "Hoofdstuk 10. Slotbepalingen" in wet_body


def test_a_repealed_article_is_kept_because_that_is_what_it_says_today(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_get(monkeypatch)

    wetten.add(tmp_path, "BWBR0045754", "woo")

    _, body = schema.parse((tmp_path / "woo" / "artikel_10-4.md").read_text(encoding="utf8"))
    assert body == "Vervallen"


def test_an_article_with_two_variants_keeps_the_order_the_law_is_written_in() -> None:
    _, articles = wetten._parse_toestand(WOO_TOESTAND)

    elektronisch = next(a for a in articles if a.nr == "10.3")

    # Each note stays above the lid it introduces, so a reader sees which
    # variant applies.
    assert elektronisch.text == (
        "Dit artikel is in werking getreden in verband met de invoering van digitaal procederen."
        "\n\n1. Het verzoek wordt langs elektronische weg ingediend."
        "\n\nVoor overige gevallen luidt het artikel als volgt:\nArtikel 10.3."
        "\n\n1. Het verzoek wordt schriftelijk ingediend."
    )


def test_the_short_title_of_a_law_leaves_out_the_registers_own_bookkeeping() -> None:
    short_title, _ = wetten._parse_toestand(WOO_TOESTAND)

    assert short_title == "Wet open overheid"  # the <citeertitel> also carries <meta-data>


def test_a_table_of_contents_gives_one_line_per_article(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_get(monkeypatch)

    wetten.add(tmp_path, "BWBR0045754", "woo")

    _, wet_body = schema.parse((tmp_path / "woo" / "_wet.md").read_text(encoding="utf8"))
    assert "- Artikel 10.1 — Intrekking Wet openbaarheid van bestuur" in wet_body


def test_an_article_nested_in_a_paragraaf_still_belongs_to_its_hoofdstuk() -> None:
    _, articles = wetten._parse_toestand(PARAGRAAF_TOESTAND)

    assert [a.nr for a in articles] == ["3.1", "3.2"]
    assert articles[0].hoofdstuk == "3. Bezwaar en beroep"
    assert articles[0].secties == ["Paragraaf 3.1. Bezwaar"]
    assert articles[0].text == "Het bezwaarschrift wordt ingediend binnen zes weken."
    # A paragraaf inside an afdeling keeps both names, not only the deepest one.
    assert articles[1].secties == ["Afdeling 3.2. Beroep", "Paragraaf 3.2.1. Algemeen"]


def test_the_table_of_contents_names_the_section_an_article_sits_under(tmp_path: Path) -> None:
    short_title, articles = wetten._parse_toestand(PARAGRAAF_TOESTAND)
    law = wetten.Law(
        bwb_id="BWBR9999999",
        title="Voorbeeldwet",
        short_title=short_title,
        valid_from="2024-01-01",
        source="https://example.invalid/toestand.xml",
        articles=articles,
    )

    wetten.write(tmp_path, "voorbeeldwet", law)

    _, body = schema.parse((tmp_path / "voorbeeldwet" / "_wet.md").read_text(encoding="utf8"))
    assert "## Hoofdstuk 3. Bezwaar en beroep" in body
    # The Awb names nothing at article level, so the section is the only wording
    # a person navigates by.
    assert body.index("### Paragraaf 3.1. Bezwaar") > body.index("## Hoofdstuk 3.")
    assert body.index("- Artikel 3.1 — Termijn") > body.index("### Paragraaf 3.1.")
    assert body.index("### Afdeling 3.2. Beroep") < body.index("### Paragraaf 3.2.1. Algemeen")


def test_an_article_the_law_gave_no_name_gets_no_dash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_get(monkeypatch)

    wetten.add(tmp_path, "BWBR0045754", "woo")

    _, wet_body = schema.parse((tmp_path / "woo" / "_wet.md").read_text(encoding="utf8"))
    assert "- Artikel 10.4" in wet_body.splitlines()  # all 570 Awb articles are nameless


def test_a_law_with_no_toestand_currently_in_force_refuses_to_guess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def get(url: str, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(SRU_RESPONSE_NO_CURRENT)

    monkeypatch.setattr("odas.wetten.httpx.get", get)

    with pytest.raises(LookupError, match="BWBR0045754"):
        wetten.fetch("BWBR0045754")


def test_updating_a_law_that_was_never_added_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="woo"):
        wetten.update(tmp_path, "woo")


def test_an_empty_data_dir_tracks_no_laws(tmp_path: Path) -> None:
    assert wetten.tracked(tmp_path) == []


def test_updating_a_tracked_law_refetches_it_by_its_own_bwb_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_get(monkeypatch)
    wetten.add(tmp_path, "BWBR0045754", "woo")

    law = wetten.update(tmp_path, "woo")

    assert law.bwb_id == "BWBR0045754"
    rows = wetten.tracked(tmp_path)
    assert [r["slug"] for r in rows] == ["woo"]
    assert rows[0]["title"] == "Wet open overheid"


def test_the_cli_adds_and_then_lists_a_law(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_get(monkeypatch)
    runner = CliRunner()

    added = runner.invoke(app, ["wetten", "add", "BWBR0045754", "woo"])

    assert added.exit_code == 0, added.output
    assert "Wet open overheid" in added.output
    assert (tmp_path / "wetten" / "woo" / "_wet.md").is_file()

    listed = runner.invoke(app, ["wetten", "list"])

    assert listed.exit_code == 0, listed.output
    assert "woo: Wet open overheid" in listed.output


def test_the_cli_says_how_many_articles_an_update_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_get(monkeypatch)
    runner = CliRunner()
    runner.invoke(app, ["wetten", "add", "BWBR0045754", "woo"])

    updated = runner.invoke(app, ["wetten", "update"])

    assert updated.exit_code == 0, updated.output
    assert "woo: Wet open overheid (7 artikelen, geldig vanaf 2026-08-15)" in updated.output


def test_the_cli_says_what_it_is_doing_while_it_fetches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_get(monkeypatch)
    runner = CliRunner()
    runner.invoke(app, ["wetten", "add", "BWBR0045754", "woo"])

    updated = runner.invoke(app, ["wetten", "update"])

    lines = [line for line in updated.output.splitlines() if line.strip()]
    assert lines[0] == "woo: BWBR0045754 opzoeken in het register…"
    assert lines[2] == f"  bron: {TOESTAND_URL}"


def test_the_cli_refuses_to_update_when_nothing_is_tracked(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["wetten", "update"])

    assert result.exit_code == 1
    assert "Geen wetten" in result.output
