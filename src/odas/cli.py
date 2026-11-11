"""Command-line interface for odas."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

# cli_summaries registers `summarize` and `summary` on the Typer cli_documents owns.
from odas import (  # noqa: F401
    cli_agent,
    cli_clean,
    cli_demo,
    cli_documents,
    cli_log,
    cli_summaries,
    cli_zaak,
)

if TYPE_CHECKING:
    from .appconfig import Field

app = typer.Typer(help="ODAS: web server and zaken validation.", no_args_is_help=True)
config_app = typer.Typer(help="Inspect and validate the data dir's schema.", no_args_is_help=True)
app.add_typer(config_app, name="config")
wetten_app = typer.Typer(help="Manage cached law text in the data dir.", no_args_is_help=True)
app.add_typer(wetten_app, name="wetten")
app.add_typer(cli_documents.app, name="index")
app.add_typer(cli_agent.app, name="agent")
app.add_typer(cli_demo.app, name="demo")
app.add_typer(cli_log.app, name="log")
# Reading a case is the common job, so these verbs sit at the top level.
app.command("info")(cli_agent.info)
app.command("list")(cli_zaak.list_)
app.command("show")(cli_zaak.show)
app.command("files")(cli_zaak.files)
app.command("clean-log")(cli_clean.clean_log)


def _fixup_dumped_fields(
    dumped_group: dict[str, dict[str, object]], group: dict[str, dict[str, Field]]
) -> None:
    """`type` is a ClassVar (model_dump never sees it); `editable` dumps as a frozenset,
    which yaml.safe_dump cannot serialize.
    """
    for section, fields in group.items():
        for key, f in fields.items():
            if f.type != "str":
                entry = dumped_group[section].setdefault(key, {})
                assert isinstance(entry, dict)
                entry["type"] = f.type
            entry = dumped_group[section].get(key)
            if isinstance(entry, dict) and isinstance(entry.get("editable"), frozenset):
                entry["editable"] = sorted(entry["editable"])


def _resolved_yaml() -> str:
    import yaml

    from .appconfig import get_config
    from .typeregistry import BASE_TYPE_SPECS

    # sort_keys=False: declaration order is the field order, on disk and in the UI.
    # exclude_defaults: only what the config actually sets, so the output stays readable.
    config = get_config()
    dumped = config.model_dump(exclude_defaults=True)
    _fixup_dumped_fields(dumped["fields"], config.fields)
    if "types" in dumped:
        _fixup_dumped_fields(dumped["types"], config.types)
        # Base fields are always re-injected on load; writing them back would collide.
        for entry in dumped["types"].values():
            for key in BASE_TYPE_SPECS:
                entry.pop(key, None)
    return yaml.safe_dump(dumped, sort_keys=False, allow_unicode=True)


@config_app.command("show")
def config_show() -> None:
    """Print the configuration this data dir carries, as the app understands it."""
    from . import __version__
    from .configload import config_path
    from .dataversion import DATA_VERSION

    typer.echo(f"# app={__version__}, layout={DATA_VERSION}, config: {config_path()}")
    typer.echo(_resolved_yaml())


def _missing_credentials() -> list[str]:
    """Credentials a configured feature needs but the data dir does not carry."""
    from .appconfig import get_config
    from .appsecrets import get_secrets

    config, secrets = get_config(), get_secrets()
    needed = {
        "oidc_client_secret": bool(config.oidc.issuer),
        "pocket_id_api_key": bool(config.oidc.issuer),
        "smtp_pass": bool(config.smtp.user),
        "ai_api_key": config.ai is not None,
    }
    return [name for name, required in needed.items() if required and not getattr(secrets, name)]


@config_app.command("check")
def config_check() -> None:
    """Validate the configuration without starting the server."""
    from .appconfig import get_config
    from .appsecrets import secrets_path

    get_config()
    missing = _missing_credentials()
    if missing:
        typer.echo(f"Configuration is valid, but {secrets_path()} is missing:")
        for name in missing:
            typer.echo(f"  {name}")
        raise typer.Exit(code=1)
    typer.echo("Configuration is valid.")


@app.command()
def init(
    force: bool = typer.Option(False, help="Overwrite the existing schema."),
) -> None:
    """Give a new data dir its schema and an empty secrets file."""
    import os

    from . import appsecrets
    from .config import Config
    from .configload import TEMPLATE

    config = Config()
    config.ensure_dirs()
    target = config.data_dir / "config.yaml"
    if target.exists() and not force:
        # The schema is what every zaak on disk is read through: never clobber it.
        typer.echo(f"{target} already exists; use --force to overwrite.")
        raise typer.Exit(code=1)
    # Copied verbatim, comments and all: the file is meant to be read and edited.
    target.write_text(TEMPLATE.read_text(encoding="utf8"), encoding="utf8")
    typer.echo(f"Written: {target}")

    # Never covered by --force: a rerun that wiped a credential would take the
    # deployment down, and the schema is the only thing --force is about.
    secrets = appsecrets.secrets_path()
    if not secrets.exists():
        secrets.write_text(appsecrets.TEMPLATE, encoding="utf8")
        os.chmod(secrets, appsecrets.FILE_MODE)
        typer.echo(f"Written: {secrets}")


@app.command()
def serve(
    no_auth: bool = typer.Option(False, "--no-auth", help="Local dev: skip the sign-in."),
    port: int | None = typer.Option(None, help="Override the port the data dir declares."),
) -> None:
    """Run the FastAPI web server (uvicorn)."""
    import os

    from . import server

    # A real data dir points the identity provider back at the deployed host, so
    # a local run has to answer for itself who is signed in.
    if no_auth:
        os.environ["ODAS_TEST_MODE"] = "1"
    server.main(port=port)


@app.command()
def mailin() -> None:
    """Receive mail on the zaak addresses and file it (SMTP daemon)."""
    from . import dataversion
    from .logging import setup_logging
    from .mailin_server import run

    setup_logging("mail")  # nobody watches this process: what it filed has to be on disk
    dataversion.ensure()
    run()


@app.command()
def upgrade(
    apply: bool = typer.Option(False, help="Write the changes; without it the plan is printed."),
) -> None:
    """Take this data dir up to the layout the app needs.

    The app does this itself at start. Run it by hand to read the plan first, or
    against a volume whose container is not running.
    """
    from . import dataversion, migrations
    from .configload import config_path

    data_dir = config_path().parent.parent
    version = dataversion.read_version()
    if version is None:
        typer.echo(f"{config_path()} declares no `version:`; see scripts/README.md.")
        raise typer.Exit(code=1)
    migrations.run(data_dir, version, dataversion.DATA_VERSION, apply=apply)


@wetten_app.command("add")
def wetten_add(bwb_id: str, slug: str) -> None:
    """Fetch a law by its BWB-ID (e.g. BWBR0045754) and track it under this slug."""
    from .config import Config
    from .wetten import add

    typer.echo(f"{slug}: {bwb_id} opzoeken in het register…")
    law = add(Config().wetten_dir, bwb_id, slug)
    typer.echo(
        f"{slug}: {law.title} ({len(law.articles)} artikelen, geldig vanaf {law.valid_from})"
    )
    typer.echo(f"  bron: {law.source}")


@wetten_app.command("update")
def wetten_update(
    slug: str = typer.Argument(None, help="Only this law; omit to refresh every tracked law."),
) -> None:
    """Refetch tracked law text to its current toestand."""
    from .config import Config
    from .wetten import tracked, update

    root = Config().wetten_dir
    rows = {row["slug"]: row for row in tracked(root)}
    slugs = [slug] if slug else list(rows)
    if not slugs:
        typer.echo("Geen wetten bijgehouden.")
        raise typer.Exit(code=1)
    for s in slugs:
        typer.echo(f"{s}: {rows.get(s, {}).get('bwb_id', s)} opzoeken in het register…")
        law = update(root, s)
        typer.echo(
            f"{s}: {law.title} ({len(law.articles)} artikelen, geldig vanaf {law.valid_from})"
        )
        typer.echo(f"  bron: {law.source}")


@wetten_app.command("list")
def wetten_list() -> None:
    """Show every law tracked in this data dir."""
    from .config import Config
    from .wetten import tracked

    root = Config().wetten_dir
    rows = tracked(root)
    if not rows:
        typer.echo("Geen wetten bijgehouden.")
        return
    for row in rows:
        typer.echo(
            f"{row['slug']}: {row['short_title']} "
            f"(geldig vanaf {row['valid_from']}, opgehaald {row['fetched_at']})"
        )


@app.command("mail")
def mail_test(to: str) -> None:
    """Send one test message, to prove the transport from the machine that runs it."""
    from . import mail
    from .appconfig import smtp
    from .logging import setup_logging

    setup_logging("app")  # the stack trace belongs in the log; the terminal gets the reason

    config = smtp()
    if not config.host:
        typer.echo("No transport: smtp.host is empty, so nothing is sent.")
        raise typer.Exit(code=1)

    where = f"{config.host}:{config.port}"
    body = f"This is a test message from ODAS. Transport: {where}."
    try:
        mail.send([to], "ODAS test", body)
    except mail.MailError as e:
        typer.echo(f"Not sent over {where}: {e}")
        raise typer.Exit(code=1) from e
    typer.echo(f"Sent to {to} over {where}.")


@app.command()
def check() -> None:
    """Validate the zaken database; exit non-zero if any zaak has problems."""
    from . import dataversion, zaak

    dataversion.ensure()
    problems = zaak.check_all()
    for p in problems:
        typer.echo(f"{p.path}: {p.message}")
    if problems:
        refs = {p.ref for p in problems}
        typer.echo(f"\n{len(problems)} problem(s) in {len(refs)} zaken.")
        raise typer.Exit(code=1)
    typer.echo("All zaken are valid.")
