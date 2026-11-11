"""The data dir carries its own schema in `.app/config.yaml`, and nothing else does."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import VMS_ZAAK, use_config, use_example_data, write_config

from odas import zaak, zaak_create
from odas.appconfig import get_config


def test_example_data_is_a_valid_data_dir_on_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point ODAS at a data dir and it knows its schema. Nothing else to configure."""
    use_example_data("vms", tmp_path, monkeypatch)

    assert get_config().org.app_title == "Mooi Stroomdal"
    assert zaak.check_all() == []  # every zaak validates against the schema it ships with


def test_an_organisation_without_dossiers_has_no_dossier_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the config does not declare does not exist: absence, not a removal rule."""
    use_example_data("vms", tmp_path, monkeypatch)

    assert "dossier" not in get_config().types
    with pytest.raises(ValueError, match="Onbekend type"):
        zaak_create.create_minimal("Een dossier", "dossier")


def test_a_data_dir_without_a_config_says_how_to_make_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    (tmp_path / ".app" / "config.yaml").unlink(missing_ok=True)
    get_config.cache_clear()

    with pytest.raises(ValueError, match="odas init"):
        get_config()


def test_init_writes_a_config_a_new_data_dir_can_work_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`odas init` is the only way a data dir gets its first schema."""
    from typer.testing import CliRunner

    from odas.cli import app as cli

    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    (tmp_path / ".app" / "config.yaml").unlink(missing_ok=True)
    assert CliRunner().invoke(cli, ["init"]).exit_code == 0
    get_config.cache_clear()

    z = zaak_create.create_minimal("Eerste zaak", "procedure")
    folder = zaak.find(z.ref)
    assert folder is not None
    assert zaak.load(folder).frontmatter["titel"] == "Eerste zaak"


def test_init_refuses_to_overwrite_an_existing_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The schema is the data dir's spec; clobbering it would orphan every zaak."""
    from typer.testing import CliRunner

    from odas.cli import app as cli

    use_config(tmp_path, monkeypatch, app_title="Eigen titel")
    before = (tmp_path / ".app" / "config.yaml").read_text(encoding="utf8")

    assert CliRunner().invoke(cli, ["init"]).exit_code != 0
    assert (tmp_path / ".app" / "config.yaml").read_text(encoding="utf8") == before


def test_the_schema_on_disk_is_the_only_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No base layer merges in behind it: a narrow config stays narrow."""
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    write_config(
        tmp_path,
        {
            "org": {"app_title": "Buurtdossiers"},
            "types": {"melding": {"wijk": {"type": ["noord", "zuid"]}}},
            "fields": {"log": {"onderwerp": "str", "aan": "list[email]", "verzonden": "datetime"}},
        },
    )
    config = get_config()

    assert set(config.types) == {"melding"}  # no procedure, no dossier leaking in
    assert config.org.app_title == "Buurtdossiers"
    assert config.oidc.group_team == "team"  # an undeclared section falls back to its defaults
    assert config.types["melding"]["wijk"].values == ["noord", "zuid"]


def test_editing_the_schema_changes_what_a_zaak_shows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file is the seam: add a field to it and the zaak has that field."""
    use_example_data("vms", tmp_path, monkeypatch)
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["types"]["procedure"]["wijk"] = {"type": ["noord", "zuid"], "label": "Wijk"}
    write_config(tmp_path, config)

    folder = zaak.find(VMS_ZAAK)
    assert folder is not None
    assert "wijk" in zaak.load(folder).fields
    assert zaak.load(folder).fields["wijk"].label == "Wijk"
