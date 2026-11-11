"""The data dir's configuration: shorthand parsing, the type registry, the schema file."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import SOLO_ZAAK, VMS_ZAAK, use_config, use_example_data, write_config
from fastapi.testclient import TestClient
from pydantic import ValidationError

from odas import configload
from odas.appconfig import (
    AppConfig,
    Field,
    field_for_key,
    get_config,
    log_fields,
    type_fields,
    type_prefix,
)
from odas.fields import FIELD_TYPES, SoortField

# The shipped template, unexpanded, as a new data dir receives it.
_TEMPLATE: dict[str, Any] = yaml.safe_load(configload.TEMPLATE.read_text(encoding="utf8"))
BASE_TYPES: dict[str, dict[str, Any]] = _TEMPLATE["types"]
LOG_FIELDS: dict[str, Any] = _TEMPLATE["fields"]

BASE_TYPE_KEYS = ("id", "soort", "titel", "aangemaakt", "gewijzigd")


def _types(**procedure: Any) -> dict[str, Any]:
    """The base registry with the `procedure` type extended."""
    return {**BASE_TYPES, "procedure": {**BASE_TYPES["procedure"], **procedure}}


def _config(**kwargs: Any) -> AppConfig:
    return AppConfig(fields=LOG_FIELDS, **kwargs)


def _one(spec: Any) -> Field:
    return _config(types=_types(proef=spec)).types["procedure"]["proef"]


@pytest.mark.parametrize(
    ("spec", "type_", "multi"),
    [
        ("str", "str", False),
        ("text", "text", False),
        ("date", "date", False),
        ("email", "email", False),
        ("latlon", "latlon", False),
        ("user", "user", False),
        ("ref", "ref", False),
        ("token", "token", False),
        ("datetime", "datetime", False),
        ("list[email]", "list[email]", True),
        (["a", "b"], "enum", False),
    ],
)
def test_type_shorthand(spec: object, type_: str, multi: bool) -> None:
    f = _one(spec)
    assert (f.type, f.multi) == (type_, multi)
    assert f.editable == {"team"}  # default: only the team edits, nothing is public
    assert f.public is False


def test_enum_shorthand_labels_default_to_the_value() -> None:
    f = _one(["nieuw", {"value": "af", "label": "Afgerond", "css": "status-done"}])
    assert f.values == ["nieuw", "af"]
    assert (f.options[0].label, f.options[0].css) == ("nieuw", "")
    assert (f.options[1].label, f.options[1].css) == ("Afgerond", "status-done")


def test_label_defaults_to_the_key() -> None:
    assert _one("str").label == "Proef"
    assert _config(types=_types(contact_naam="str")).types["procedure"]["contact_naam"].label


def test_long_form_carries_flags() -> None:
    f = _one({"type": "str", "label": "Wijk", "hint": "buurt", "public": True})
    assert (f.label, f.hint, f.public) == ("Wijk", "buurt", True)


def test_editable_accepts_a_yaml_list_and_coerces_to_frozenset() -> None:
    f = _one({"type": "str", "public": True, "editable": ["team", "public"]})
    assert f.editable == frozenset({"team", "public"})


def test_editable_rejects_an_unknown_role() -> None:
    with pytest.raises(ValidationError, match=r"public.*team|team.*public"):
        _one({"type": "str", "editable": ["expert"]})


def test_editable_public_requires_public_true() -> None:
    with pytest.raises(ValidationError, match="public"):
        _one({"type": "str", "editable": ["public"]})


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown type"):
        _one("kleur")


def test_unknown_attribute_is_rejected() -> None:
    """extra=forbid: a typo in the config must not be silently ignored."""
    with pytest.raises(ValidationError):
        _one({"type": "str", "lable": "Wijk"})


def test_dropping_a_log_key_the_code_needs_is_rejected() -> None:
    log = {k: v for k, v in LOG_FIELDS["log"].items() if k != "onderwerp"}
    with pytest.raises(ValidationError, match="onderwerp"):
        AppConfig(fields={"log": log}, types=BASE_TYPES)


def test_the_data_dir_declares_its_identity_provider_mail_and_server_settings() -> None:
    """One file shows who signs users in, where mail goes, and how the server runs."""
    cfg = _config(
        oidc={
            "issuer": "https://id.example.nl/",
            "client_id": "odas",
            "redirect_uri": "https://odas.example.nl/auth/callback",
            "group_team": "veenwacht_team",
        },
        smtp={"host": "mail.example.nl", "port": 587, "sender": "noreply@example.nl"},
        server={"log_level": "DEBUG", "host": "127.0.0.1", "port": 9000},
    )
    assert cfg.oidc.issuer == "https://id.example.nl"  # the trailing slash is dropped
    assert (cfg.oidc.client_id, cfg.oidc.group_team) == ("odas", "veenwacht_team")
    assert (cfg.smtp.host, cfg.smtp.port, cfg.smtp.sender) == (
        "mail.example.nl",
        587,
        "noreply@example.nl",
    )
    assert (cfg.server.log_level, cfg.server.host, cfg.server.port) == ("DEBUG", "127.0.0.1", 9000)


def test_a_config_that_declares_no_transport_falls_back_to_neutral_defaults() -> None:
    """Nothing merges behind the file, so an undeclared section is the model default."""
    cfg = _config()
    assert cfg.oidc.issuer == ""  # no identity provider: sign-in is not configured
    assert cfg.oidc.group_team == "team"
    assert cfg.smtp.host == ""  # empty host: mail is logged, never sent
    assert (cfg.server.log_level, cfg.server.port) == ("INFO", 8000)


def test_a_secret_may_not_be_declared_in_the_configuration_file() -> None:
    """Secrets live in `.app/secrets.yaml`; the schema file rejects them outright."""
    with pytest.raises(ValidationError, match="smtp_pass"):
        _config(smtp={"host": "mail.example.nl", "smtp_pass": "hunter2"})
    with pytest.raises(ValidationError, match="client_secret"):
        _config(oidc={"issuer": "https://id.example.nl", "client_secret": "hunter2"})


def test_the_org_section_carries_branding_only() -> None:
    """Transport settings moved out of `org:`, so they cannot hide behind branding."""
    with pytest.raises(ValidationError, match="smtp_from"):
        _config(org={"display_name": "Test", "smtp_from": "noreply@example.nl"})
    with pytest.raises(ValidationError, match="oidc_group_team"):
        _config(org={"display_name": "Test", "oidc_group_team": "veenwacht_team"})


def test_the_environment_cannot_override_what_the_data_dir_declares(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ODAS_DATA_DIR picks the data dir; the data dir alone says how the app behaves."""
    write_config(
        tmp_path,
        {
            "oidc": {"issuer": "https://id.example.nl", "group_team": "veenwacht_team"},
            "smtp": {"sender": "noreply@example.nl"},
            "server": {"log_level": "WARNING"},
            "fields": LOG_FIELDS,
            "types": BASE_TYPES,
        },
    )
    monkeypatch.setenv("OIDC_GROUP_TEAM", "custom_team")
    monkeypatch.setenv("SMTP_FROM", "env@example.org")
    monkeypatch.setenv("LOG_LEVEL", "CRITICAL")

    cfg = get_config()
    assert cfg.oidc.group_team == "veenwacht_team"
    assert cfg.smtp.sender == "noreply@example.nl"
    assert cfg.server.log_level == "WARNING"


def test_the_log_level_comes_from_the_configuration_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`server.log_level` decides how loud the app is; LOG_LEVEL in the env does not."""
    write_config(
        tmp_path, {"server": {"log_level": "DEBUG"}, "fields": LOG_FIELDS, "types": BASE_TYPES}
    )
    monkeypatch.setenv("LOG_LEVEL", "CRITICAL")
    from odas.logging import setup_logging

    assert setup_logging("test-level").level == logging.DEBUG


def test_logging_still_starts_when_the_data_dir_has_no_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing config must be reported by the startup check, not by logging setup."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("ODAS_DATA_DIR", str(empty))
    get_config.cache_clear()
    from odas.logging import setup_logging

    assert setup_logging("test-noconfig").level == logging.INFO


def test_an_error_the_web_server_reports_lands_in_the_app_log(tmp_path: Path) -> None:
    """A failed request's stack trace shows on the Admin page, not only in the container log."""
    from odas.logging import setup_logging

    setup_logging("app")
    logging.getLogger("uvicorn.error").error("Exception in ASGI application")

    text = (tmp_path / ".app" / "logs" / "app.log").read_text(encoding="utf8")
    assert "[ERROR]" in text and "Exception in ASGI application" in text


def test_each_start_of_the_app_opens_a_marked_section_in_its_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator reads app.log and sees where a run starts, and which release runs."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    from odas import __version__
    from odas.app import create_app

    log_file = tmp_path / ".app" / "logs" / "app.log"
    create_app()
    before = log_file.read_text(encoding="utf8").count("*" * 60)
    create_app()
    text = log_file.read_text(encoding="utf8")

    assert text.count("*" * 60) == before + 2  # each start opens and closes its own section
    assert f"ODAS {__version__}: web app starting" in text
    assert "org:" in text and "Stichting Veenwacht" in text
    assert f"data dir:     {tmp_path.resolve()}" in text


def test_the_server_reads_its_host_and_port_from_the_configuration_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Where the process listens is declared with everything else, not in the env."""
    write_config(
        tmp_path,
        {"server": {"host": "127.0.0.1", "port": 9123}, "fields": LOG_FIELDS, "types": BASE_TYPES},
    )
    monkeypatch.setenv("PORT", "1")
    seen: dict[str, Any] = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: seen.update(kwargs))

    from odas import server

    server.main()
    assert (seen["host"], seen["port"]) == ("127.0.0.1", 9123)


def test_a_new_data_dir_starts_with_a_plain_procedure_and_not_a_helpdesk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Running `odas init` must not hand a lone jurist someone else's helpdesk to delete."""
    use_config(tmp_path, monkeypatch)
    config = get_config()
    assert set(config.types) == {"procedure", "dossier"}
    assert config.org.app_title == "ODAS"

    procedure = config.types["procedure"]
    assert "ext_instantie" in procedure  # the body on the other side of the procedure
    assert "contact_naam" not in procedure  # nobody hands a question in here
    assert "behandelaar" not in procedure  # one person works alone, so nobody is assigned


def test_an_organisation_declares_its_own_narrower_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A type is a complete declaration: vms lists what it wants and nothing more."""
    use_example_data("vms", tmp_path, monkeypatch)
    config = get_config()
    assert config.org.app_title == "Mooi Stroomdal"
    assert config.intake_type == ""  # no type claims the public form, so there is none
    assert set(config.types) == {"procedure"}  # no helpdesk here, so no hulpvraag type
    assert "behandelaar" not in config.types["procedure"]
    assert "contact_naam" not in config.types["procedure"]
    assert config.types["procedure"]["fase"].label == "Type dossier"


def test_editing_the_schema_file_adds_a_field_without_a_rebuild(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    write_config(
        tmp_path,
        {
            "org": {"app_title": "Buurtdossiers"},
            "types": {
                "hulpvraag": {
                    "status": ["nieuw", "afgerond"],
                    "wijk": {"type": ["noord", "zuid"], "label": "Wijk"},
                    "termijn_datum": "date",
                    "betrokkenen": "list[email]",
                    "reply_token": "token",
                }
            },
            "fields": LOG_FIELDS,
        },
    )
    config = get_config()
    assert config.org.app_title == "Buurtdossiers"
    assert list(config.types["hulpvraag"]) == [
        *BASE_TYPE_KEYS,
        "status",
        "wijk",
        "termijn_datum",
        "betrokkenen",
        "reply_token",
    ]
    assert config.types["hulpvraag"]["wijk"].values == ["noord", "zuid"]


def test_malformed_schema_file_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    write_config(
        tmp_path, {"types": {"hulpvraag": {"status": {"type": "kleur"}}}, "fields": LOG_FIELDS}
    )
    with pytest.raises(ValidationError, match="unknown type"):
        get_config()


def test_init_output_round_trips(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Generate-then-edit: what `odas init` writes must load back unchanged."""
    from typer.testing import CliRunner

    from odas.cli import app as cli

    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    (tmp_path / ".app" / "config.yaml").unlink(missing_ok=True)

    assert CliRunner().invoke(cli, ["init"]).exit_code == 0
    assert (tmp_path / ".app" / "config.yaml").is_file()

    get_config.cache_clear()
    assert set(get_config().types) == {"procedure", "dossier"}
    assert get_config().org.app_title == "ODAS"


def test_ui_follows_the_configured_schema(vms_client: TestClient) -> None:
    """Same image, dossier-only profile: the UI drops what the config drops."""
    edit = vms_client.get(f"/zaken/{VMS_ZAAK}/bewerken")
    assert edit.status_code == 200
    assert "Behandelaar" not in edit.text  # not declared for this org
    assert "Contactpersoon" not in edit.text
    assert "Type dossier" in edit.text  # `fase` relabelled by the profile

    detail = vms_client.get(f"/zaken/{VMS_ZAAK}")
    assert "Type dossier" in detail.text
    assert "Behandelaar" not in detail.text


def test_saving_ignores_fields_outside_the_schema(vms_client: TestClient) -> None:
    """A field the org does not declare cannot be written through the form."""
    r = vms_client.post(
        f"/zaken/{VMS_ZAAK}/bewerken",
        data={
            "mode": "form",
            "id": VMS_ZAAK,
            "status": "afgerond",
            "behandelaar": "Iemand",
            "aangemaakt": "2026-03-04T09:20:00",
            "reply_token": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    from odas import zaak

    folder = zaak.find(VMS_ZAAK)
    assert folder is not None
    z = zaak.load(folder)
    assert z.status == "afgerond"
    assert "behandelaar" not in z.frontmatter


def test_type_field_resolves_to_the_subclass() -> None:
    fields = _config(types={"hulpvraag": {"status": ["nieuw", "af"]}}).types["hulpvraag"]
    assert type(fields["soort"]) is SoortField
    assert type(fields["status"]).__name__ == "EnumField"


def test_base_fields_are_injected_in_order() -> None:
    assert list(_config(types={"discussion": {}}).types["discussion"]) == list(BASE_TYPE_KEYS)


def test_type_redeclaring_a_base_key_raises() -> None:
    with pytest.raises(ValidationError, match="titel"):
        _config(types={"discussion": {"titel": "str"}})


def test_type_fields_of_an_unknown_name_returns_just_the_base_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    use_config(tmp_path, monkeypatch)
    get_config()
    assert list(type_fields("nonexistent")) == list(BASE_TYPE_KEYS)


def test_field_for_key_finds_a_field_by_its_declared_key() -> None:
    fields = _config(types={"discussion": {}}).types["discussion"]
    assert field_for_key(fields, "titel") is fields["titel"]
    assert field_for_key(fields, "nope") is None


@pytest.mark.parametrize("name", sorted(FIELD_TYPES))
def test_every_registered_field_type_is_declarable_and_round_trips(name: str) -> None:
    """The registry is the vocabulary of the config seam: each name must be usable.

    A type nobody can write in a YAML file is not a feature, it is dead code --
    and one that is usable but undocumented is a trap. This is the whole list.
    """
    from odas import schema

    spec: object = ["a", "b"] if name == "enum" else name
    field = _one(spec)
    assert field.type == name
    assert type(field) is FIELD_TYPES[name]

    fields = {"proef": field}
    value = field.initial() or ("a" if name == "enum" else "")
    text = schema.dump(dict.fromkeys(field.disk_keys("proef"), value), "Body.", fields)
    fm, body = schema.parse(text)
    assert body == "Body."
    for key in field.disk_keys("proef"):
        assert key in fm  # every disk key it owns survives a write/read cycle


def test_config_show_prints_the_configuration_the_data_dir_carries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from odas.cli import app as cli

    use_example_data("vms", tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["config", "show"])

    assert result.exit_code == 0
    loaded = yaml.safe_load(result.stdout)
    assert loaded["org"]["app_title"] == "Mooi Stroomdal"
    assert "dossier" not in loaded["types"]  # the data dir does not declare it, so it is not shown


def test_config_check_rejects_a_broken_schema_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from odas.cli import app as cli

    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    write_config(
        tmp_path, {"types": {"hulpvraag": {"status": {"type": "kleur"}}}, "fields": LOG_FIELDS}
    )

    assert CliRunner().invoke(cli, ["config", "check"]).exit_code != 0


def test_a_data_dir_that_never_sends_mail_declares_no_recipients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A solo jurist writes letters in their own mail client, so a log entry is only a subject."""
    use_example_data("solo", tmp_path, monkeypatch)

    assert list(log_fields()) == ["aangemaakt", "gewijzigd", "onderwerp"]  # nothing is sent


def test_a_solo_data_dir_serves_its_procedures_without_any_helpdesk_page(
    solo_client: TestClient,
) -> None:
    """One jurist, no helpdesk: the zaak opens, and there is nothing to submit a question to."""
    detail = solo_client.get(f"/zaken/{SOLO_ZAAK}")
    assert detail.status_code == 200
    assert "Provincie Limburg" in detail.text  # the body on the other side of the procedure
    assert "Behandelaar" not in detail.text  # one person works here, so nobody is assigned

    assert solo_client.get("/indienen").status_code == 404  # no type declares a public intake
    root = solo_client.get("/", follow_redirects=False)
    assert root.headers["location"] == "/zaken"  # with no form, the site opens on the list


# ── A type extends a type ─────────────────────────────────────────────────────


def _extends_config(**types: Any) -> dict[str, Any]:
    return {
        "types": {
            "procedure": {"ext_instantie": "str", "fase": ["bezwaar", "beroep"]},
            **types,
        },
        "fields": LOG_FIELDS,
    }


def test_a_type_that_extends_another_starts_from_its_parents_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A hulpvraag is a procedure with a helpdesk in front of it, so it inherits the procedure."""
    write_config(
        tmp_path, _extends_config(hulpvraag={"extends": "procedure", "contact_naam": "str"})
    )

    fields = get_config().types["hulpvraag"]
    assert list(fields) == [*BASE_TYPE_KEYS, "ext_instantie", "fase", "contact_naam"]
    assert fields["ext_instantie"].label == "Ext instantie"  # the parent's declaration, verbatim


def test_a_child_may_narrow_a_field_its_parent_declared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One organisation's phases are not another's, so a child restates the field it needs."""
    write_config(
        tmp_path,
        _extends_config(
            hulpvraag={"extends": "procedure", "fase": {"type": ["intake", "afgerond"]}}
        ),
    )

    fields = get_config().types["hulpvraag"]
    assert fields["fase"].values == ["intake", "afgerond"]
    assert list(fields).index("fase") == list(get_config().types["procedure"]).index("fase")


def test_extending_a_type_that_itself_extends_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One level, never a chain: a reader must see the whole type in two places, not five."""
    with pytest.raises(ValidationError, match="extends is one level"):
        write_config(
            tmp_path,
            _extends_config(
                hulpvraag={"extends": "procedure"},
                spoedvraag={"extends": "hulpvraag"},
            ),
        )
        get_config()


def test_extending_a_type_that_does_not_exist_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(ValidationError, match="extends unknown type"):
        write_config(tmp_path, _extends_config(hulpvraag={"extends": "melding"}))
        get_config()


# ── A capability is a declaration ─────────────────────────────────────────────


def test_the_type_that_declares_public_intake_is_the_one_the_form_creates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Intake exists because a type says so, never because an org flag says so."""
    write_config(
        tmp_path, _extends_config(hulpvraag={"extends": "procedure", "public_intake": True})
    )

    assert get_config().intake_type == "hulpvraag"
    assert "public_intake" not in get_config().types["hulpvraag"]  # a capability, not a field


def test_a_data_dir_with_no_public_intake_names_no_intake_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    write_config(tmp_path, _extends_config())
    assert get_config().intake_type == ""


def test_two_types_may_not_both_claim_the_public_intake_form(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """There is one /indienen, so exactly one type may own it."""
    with pytest.raises(ValidationError, match="two types declare public_intake"):
        write_config(
            tmp_path,
            _extends_config(
                hulpvraag={"public_intake": True},
                melding={"public_intake": True},
            ),
        )
        get_config()


def test_a_type_declares_the_two_letters_in_front_of_its_refs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A ref reads as its own type: ov-12345 is an overleg, never a procedure."""
    write_config(tmp_path, _extends_config(overleg={"prefix": "ov"}))

    assert type_prefix("overleg") == "ov"
    assert "prefix" not in get_config().types["overleg"]  # a declaration, not a field


def test_a_type_that_declares_no_prefix_keeps_zk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A data dir written before prefixes existed keeps minting the refs it always did."""
    write_config(tmp_path, _extends_config())

    assert type_prefix("procedure") == "zk"


@pytest.mark.parametrize("bad", ["o", "ovl", "OV", "o1", "ov-"])
def test_a_prefix_that_is_not_two_lowercase_letters_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bad: str
) -> None:
    """`ref_from_folder` splits a folder name on its second hyphen, so the shape is fixed."""
    with pytest.raises(ValidationError, match="prefix"):
        write_config(tmp_path, _extends_config(overleg={"prefix": bad}))
        get_config()


def test_a_column_that_no_type_declares_is_left_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A field is deleted and its name stays in `org.columns`: the table drops it."""
    write_config(
        tmp_path,
        {
            "org": {"columns": ["gewijzigd", "weg_veld", "status"]},
            "fields": LOG_FIELDS,
            "types": BASE_TYPES,
        },
    )
    monkeypatch.setenv("ODAS_DATA_DIR", str(tmp_path))
    from odas import zaak_columns

    assert list(zaak_columns.defaults()) == ["gewijzigd", "status"]


def test_a_key_declared_twice_is_refused_instead_of_silently_replaced(tmp_path: Path) -> None:
    """A second `mailin:` hides the first, so the file is rejected and names the key."""
    write_config(tmp_path, "mailin:\n  port: 25\nmailin:\n  port: 2525\n")

    with pytest.raises(ValueError, match="mailin"):
        configload.resolve(str(tmp_path))


def test_a_key_declared_twice_inside_a_section_is_refused_as_well(tmp_path: Path) -> None:
    """The loss is the same at any depth, so the check is not only for the top level."""
    write_config(tmp_path, "smtp:\n  port: 25\n  port: 587\n")

    with pytest.raises(ValueError, match="port"):
        configload.resolve(str(tmp_path))


def test_without_odas_data_dir_the_current_directory_is_the_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A person runs odas inside a data dir and sets no environment variable."""
    write_config(
        tmp_path, {"org": {"display_name": "Hier"}, "fields": LOG_FIELDS, "types": BASE_TYPES}
    )
    monkeypatch.delenv("ODAS_DATA_DIR")
    monkeypatch.chdir(tmp_path)
    get_config.cache_clear()

    assert get_config().org.display_name == "Hier"


def test_odas_data_dir_wins_over_the_current_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A container sets ODAS_DATA_DIR and runs elsewhere; it still reads its data dir."""
    here, there = tmp_path / "here", tmp_path / "there"
    write_config(here, {"org": {"display_name": "Hier"}, "fields": LOG_FIELDS, "types": BASE_TYPES})
    write_config(
        there, {"org": {"display_name": "Daar"}, "fields": LOG_FIELDS, "types": BASE_TYPES}
    )
    monkeypatch.setenv("ODAS_DATA_DIR", str(there))
    monkeypatch.chdir(here)
    get_config.cache_clear()

    assert get_config().org.display_name == "Daar"
