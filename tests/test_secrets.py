"""Secrets live in `$ODAS_DATA_DIR/.app/secrets.yaml`, never in the environment."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
import yaml
from conftest import LOG_FIELDS, write_config, write_secrets
from pydantic import ValidationError
from typer.testing import CliRunner

from odas import appsecrets
from odas.cli import app as cli


def test_a_secret_is_read_from_the_data_dir(tmp_path: Path) -> None:
    """The data dir carries its own credentials, next to its own schema."""
    write_secrets(
        tmp_path,
        {
            "oidc_client_secret": "oidc-shh",
            "pocket_id_api_key": "pocket-shh",
            "smtp_pass": "mail-shh",
        },
    )
    assert appsecrets.require("oidc_client_secret") == "oidc-shh"
    assert appsecrets.require("pocket_id_api_key") == "pocket-shh"
    assert appsecrets.require("smtp_pass") == "mail-shh"


def test_the_environment_is_not_a_source_of_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leftover env var must not quietly become the credential the app signs with."""
    write_secrets(tmp_path, {"oidc_client_secret": "from-the-file"})
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "from-the-environment")
    assert appsecrets.require("oidc_client_secret") == "from-the-file"


def test_a_data_dir_without_a_secrets_file_simply_has_none(tmp_path: Path) -> None:
    """A dev data dir needs no credentials, so a missing file is not an error."""
    assert not (tmp_path / ".app" / "secrets.yaml").exists()
    assert appsecrets.get_secrets().smtp_pass == ""


def test_asking_for_a_missing_secret_names_the_file_it_belongs_in(tmp_path: Path) -> None:
    """The error tells the operator which key to add and where."""
    write_secrets(tmp_path, {"smtp_pass": "mail-shh"})
    with pytest.raises(ValueError, match="pocket_id_api_key") as err:
        appsecrets.require("pocket_id_api_key")
    assert str(tmp_path / ".app" / "secrets.yaml") in str(err.value)


def test_the_secrets_file_is_readable_only_by_its_owner(tmp_path: Path) -> None:
    """Reading the file also repairs its mode, the way the session key file does."""
    path = write_secrets(tmp_path, {"smtp_pass": "mail-shh"})
    path.chmod(0o644)
    appsecrets.get_secrets()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_an_unknown_key_in_the_secrets_file_is_rejected(tmp_path: Path) -> None:
    """A typo must fail loudly, not leave the app running without the credential."""
    write_secrets(tmp_path, {"smtp_password": "mail-shh"})
    with pytest.raises(ValidationError):
        appsecrets.get_secrets()


def test_init_gives_a_new_data_dir_a_secrets_stub(tmp_path: Path) -> None:
    """`odas init` names every credential the operator has to fill in."""
    assert CliRunner().invoke(cli, ["init", "--force"]).exit_code == 0

    path = tmp_path / ".app" / "secrets.yaml"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    written = yaml.safe_load(path.read_text(encoding="utf8"))
    assert set(written) == {
        "oidc_client_secret",
        "pocket_id_api_key",
        "smtp_pass",
        "ai_api_key",
    }
    assert appsecrets.get_secrets() == appsecrets.AppSecrets()  # a stub configures nothing


def test_init_never_overwrites_the_secrets_a_data_dir_already_has(tmp_path: Path) -> None:
    """Losing a credential to a rerun would take the deployment down."""
    path = write_secrets(tmp_path, {"smtp_pass": "mail-shh"})
    before = path.read_text(encoding="utf8")

    result = CliRunner().invoke(cli, ["init", "--force"])  # --force is about the schema

    assert path.read_text(encoding="utf8") == before
    assert result.exit_code == 0


def test_config_check_reports_a_credential_the_deployment_still_needs(tmp_path: Path) -> None:
    """Sign-in is configured but its secret is not: say so before the server starts."""
    write_config(
        tmp_path,
        {
            "oidc": {"issuer": "https://id.example.nl", "client_id": "odas"},
            "types": {"hulpvraag": {}},
            "fields": LOG_FIELDS,
        },
    )
    result = CliRunner().invoke(cli, ["config", "check"])

    assert result.exit_code == 1
    assert "oidc_client_secret" in result.output
    assert "secrets.yaml" in result.output


def test_config_show_never_prints_a_credential(tmp_path: Path) -> None:
    """The output is meant to be pasted into a ticket, so it must carry no secret."""
    write_config(tmp_path, {"types": {"hulpvraag": {}}, "fields": LOG_FIELDS})
    write_secrets(tmp_path, {"smtp_pass": "mail-shh", "pocket_id_api_key": "pocket-shh"})

    result = CliRunner().invoke(cli, ["config", "show"])

    assert result.exit_code == 0
    assert "mail-shh" not in result.output
    assert "pocket-shh" not in result.output
