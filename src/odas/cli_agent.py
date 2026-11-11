"""`odas info` and `odas agent init`: which volume this is, and what it carries.

`info` answers the first question a terminal has, and it answers it on a stale
volume too: it reports a layout mismatch, it never refuses and never migrates.

The layout and the text that describes it ship together, so a volume teaches a
reader its own layout and a layout change reaches every volume in one command.
"""

from __future__ import annotations

from pathlib import Path

import typer

TEMPLATES = Path(__file__).resolve().parent / "builtin" / "agent"
# (what ships in the package, where it lands on the volume)
FILES = (
    ("CLAUDE.md", Path("CLAUDE.md")),
    ("skills/summarize/SKILL.md", Path(".claude") / "skills" / "summarize" / "SKILL.md"),
)

app = typer.Typer(
    help="The instructions this data dir carries for a person or an agent reading it.",
    no_args_is_help=True,
)


@app.command()
def init(force: bool = typer.Option(False, help="Overwrite what is already there.")) -> None:
    """Write this data dir's CLAUDE.md and its summarize skill."""
    from .config import Config

    root = Config().root
    targets = [(TEMPLATES / source, root / rel) for source, rel in FILES]
    existing = [str(target) for _, target in targets if target.exists()]
    if existing and not force:
        # A volume's own notes are not scratch: say what stands, and change nothing.
        typer.echo("Already there; use --force to overwrite:")
        for name in existing:
            typer.echo(f"  {name}")
        raise typer.Exit(code=1)
    for source, target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Copied verbatim: the file is meant to be read, and edited on the volume.
        target.write_text(source.read_text(encoding="utf8"), encoding="utf8")
        typer.echo(f"Written: {target}")


def _layout_line() -> str:
    """What the app wants, what the folder declares, and whether they agree."""
    from . import dataversion
    from .configload import config_path

    want = dataversion.DATA_VERSION
    if not config_path().is_file():
        # No schema is not a stale volume: pointing the migration hint at it misleads.
        return f"{want} (app); this is not a data dir yet, run `odas init`"
    have = dataversion.read_version()
    if have == want:
        return f"{want}"
    return f"{want} (app) / {have or 'none'} (data) -- run `odas upgrade`"


def _zaken_count() -> str:
    """Folders under zaken/, which needs no schema: it still counts a stale volume."""
    from . import zaak

    try:
        return str(len(zaak.list_ids()))
    except OSError:
        return "-"


def info() -> None:
    """Print where this command runs, which data dir it reads, and what is in it."""
    import os

    from . import __version__
    from .appsecrets import secrets_path
    from .config import Config
    from .configload import config_path

    root = Config().root
    source = "ODAS_DATA_DIR" if os.getenv("ODAS_DATA_DIR") else "cwd"
    secrets = secrets_path()
    rows = {
        "cwd": str(Path.cwd()),
        "data": f"{root} ({source})" + ("" if root.is_dir() else " -- missing"),
        "config": str(config_path()),
        "secrets": f"{secrets}" + ("" if secrets.is_file() else " -- missing"),
        "app": __version__,
        "layout": _layout_line(),
        "zaken": _zaken_count(),
    }
    for label, value in rows.items():
        typer.echo(f"{label + ':':<9}{value}")
