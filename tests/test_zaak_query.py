"""The overview list: which zaken a viewer sees, in what order, under which heading.

This is the read side of the application interface. The index page renders whatever
these functions return, so the rules about scope, ordering and grouping are stated
here once, against the example data, without going through HTTP or HTML.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import GRANTEE, LEEG, VEENWACHT_ZAKEN, ZAAK, use_example_data, write_config

from odas.access import Viewer

UNGRANTED = "zk-93810"  # an example zaak GRANTEE is not named in


def team() -> "Viewer":
    return Viewer(email="t.team@example.org", is_team=True)


def test_a_team_member_sees_every_zaak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import zaak_query

    assert len(zaak_query.visible(team())) == VEENWACHT_ZAKEN


def test_a_grantee_sees_only_the_zaken_that_name_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import zaak_query

    refs = [z.ref for z in zaak_query.visible(Viewer(email=GRANTEE))]
    assert refs == [ZAAK]  # the one zaak whose toegang: field names them


def test_a_user_with_no_grant_sees_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import zaak_query

    assert zaak_query.visible(Viewer(email="nobody@example.org")) == []


def test_filtering_by_soort_returns_only_that_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import zaak_query

    dossiers = zaak_query.of_soort(zaak_query.visible(team()), "dossier")
    assert dossiers  # the example data has two
    assert {z.soort for z in dossiers} == {"dossier"}


def test_the_most_recently_changed_zaak_is_listed_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Overview order is last-change-first."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import zaak_query

    assert zaak_query.visible(team())[0].ref == LEEG  # gewijzigd 2026-07-26, the newest


def test_every_type_that_has_zaken_offers_a_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import zaak_query

    counts = {
        name: (label, n) for name, label, n in zaak_query.soort_counts(zaak_query.visible(team()))
    }
    assert counts["hulpvraag"] == ("Hulpvraag", 5)
    assert counts["dossier"] == ("Dossier", 2)  # the label comes from the config, not the key


def test_a_type_without_zaken_offers_no_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A declared type with no zaken must not offer an empty page."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import zaak_query

    only_dossiers = zaak_query.of_soort(zaak_query.visible(team()), "dossier")
    assert [name for name, _, _ in zaak_query.soort_counts(only_dossiers)] == ["dossier"]


def test_a_zaak_of_an_undeclared_soort_is_listed_under_overig(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A soort the config no longer declares still has to appear; data outlives schema."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    del config["types"]["hulpvraag"]  # the org retires a type; its zaken stay on disk
    write_config(tmp_path, config)
    from odas import zaak_query

    zaken = zaak_query.visible(team())
    assert ("overig", "Overig", 5) in zaak_query.soort_counts(zaken)
    assert ZAAK in [z.ref for z in zaak_query.of_soort(zaken, "overig")]
    assert ZAAK not in [z.ref for z in zaak_query.of_soort(zaken, "dossier")]


# ── Narrowing ─────────────────────────────────────────────────────────────────


def test_a_term_matches_the_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import zaak_query

    assert [z.ref for z in zaak_query.visible(team(), q=ZAAK)] == [ZAAK]


def test_a_sleutel_waarde_term_matches_that_key_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every declared field is a facet, because the term names the key, not a code path."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import zaak_query

    found = zaak_query.visible(team(), q="fase:bezwaar")
    assert found
    assert {z.frontmatter["fase"] for z in found} == {"bezwaar"}


def test_narrowing_never_widens_what_a_grantee_sees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Access comes first, always."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import zaak_query

    assert [z.ref for z in zaak_query.visible(Viewer(email=GRANTEE), q=UNGRANTED)] == []


def test_narrowing_by_status_returns_only_that_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The status choice is the same narrowing as typing it in the box."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import zaak_query

    found = zaak_query.visible(team(), status="nieuw")
    assert found
    assert {z.frontmatter["status"] for z in found} == {"nieuw"}


# ── What the choices are made of ──────────────────────────────────────────────


def test_the_columns_on_offer_are_every_list_field_and_the_defaults_are_the_named_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """solo names ext_ref and not ext_instantie: both are on offer, one by default."""
    use_example_data("solo", tmp_path, monkeypatch)
    from odas import zaak_columns

    assert zaak_columns.candidates()["ext_instantie"].label == "Instantie"
    assert "toegang" not in zaak_columns.candidates()  # an access rule is no fact to list
    assert "ext_ref" in zaak_columns.defaults()
    assert "ext_instantie" not in zaak_columns.defaults()


def test_the_statuses_on_offer_come_from_the_declared_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """vms declares three values of its own; the code names none of them."""
    use_example_data("vms", tmp_path, monkeypatch)
    from odas import zaak_query

    assert zaak_query.status_options() == [
        ("nieuw", "Nieuw"),
        ("in_behandeling", "In behandeling"),
        ("afgerond", "Afgerond"),
    ]


def test_an_unclosed_quote_still_narrows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A person types the opening quote before the closing one; the page must not break."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import zaak_query

    assert [z.ref for z in zaak_query.visible(team(), q='"euromast')] == ["zk-93810"]
