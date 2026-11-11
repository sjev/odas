"""`odas demo init` and `odas demo reset`: seed and empty the public demonstration.

Only `config.yaml` ships inside the package. The zaken are generated fresh at
init/reset time (`demo_seed.py`), and the law text is fetched from the public
register once and then left alone. The reset replaces what a visitor can touch
and leaves `.app/` alone, so the config, the signing key and the delivery trail
survive the hour.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path

import typer

from odas import demo_seed

SEED = Path(__file__).resolve().parent / "builtin" / "demo"

app = typer.Typer(help="Seed and reset the public demonstration.", no_args_is_help=True)


def _replace(source: Path, target: Path) -> None:
    """Swap a directory for the seed's copy of it, with one rename as the gap.

    A rename over a non-empty directory fails, so the old one steps aside first.
    Between the two renames the directory is absent, and a request that lands
    there reads an empty store rather than a half-written one.
    """
    staged = target.with_name(f"{target.name}.new")
    if staged.exists():
        shutil.rmtree(staged)
    if source.is_dir():
        shutil.copytree(source, staged)
    else:
        staged.mkdir(parents=True)

    old = target.with_name(f"{target.name}.old")
    if old.exists():
        shutil.rmtree(old)
    if target.exists():
        target.rename(old)
    staged.rename(target)
    if old.exists():
        shutil.rmtree(old)


def _refresh_termijnen() -> None:
    """Move every deadline the seed carries to `demo_seed.TERMIJN_DAYS` from today."""
    from odas import index_write, zaak

    due = (date.today() + timedelta(days=demo_seed.TERMIJN_DAYS)).isoformat()
    for z in zaak.list_all():
        if z.frontmatter.get("termijn_datum"):
            folder = zaak.find(z.ref)
            if folder is not None:
                index_write.set_field(folder, "termijn_datum", due, by="demo")


def _rebuild_zaken(target: Path) -> None:
    """Regenerate the demo's zaken in a scratch data dir, then swap them into `target`.

    Runs `demo_seed.build_zaken()` against a throwaway `ODAS_DATA_DIR`, so the
    live data dir is never half-written. Safe only because `odas demo reset`
    always runs as its own process, never inside the running web server.
    """
    from .appconfig import get_config
    from .config import Config

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        (scratch / ".app").mkdir()
        shutil.copy(SEED / "config.yaml", scratch / ".app" / "config.yaml")

        previous = os.environ.get("ODAS_DATA_DIR")
        os.environ["ODAS_DATA_DIR"] = str(scratch)
        get_config.cache_clear()
        try:
            demo_seed.build_zaken()
            _replace(Config().zaken_dir, target)
        finally:
            if previous is None:
                os.environ.pop("ODAS_DATA_DIR", None)
            else:
                os.environ["ODAS_DATA_DIR"] = previous
            get_config.cache_clear()


@app.command("reset")
def reset() -> None:
    """Put the seeded zaken back and throw away everything a visitor left."""
    from .config import Config

    config = Config()
    config.ensure_dirs()
    _rebuild_zaken(config.zaken_dir)
    _replace(SEED / "prullenbak", config.prullenbak_dir)
    demo_seed.fetch_wetten(config.wetten_dir)  # leaves the laws already on disk alone
    _refresh_termijnen()
    typer.echo(f"Demo reset: {config.zaken_dir}")


@app.command("init")
def init(
    force: bool = typer.Option(False, help="Overwrite the existing schema."),
) -> None:
    """Give this data dir the demo's schema, then seed it. Run once, at deploy."""
    from .appconfig import get_config
    from .config import Config

    config = Config()
    config.ensure_dirs()
    target = config.data_dir / "config.yaml"
    if target.exists() and not force:
        typer.echo(f"{target} already exists; use --force to overwrite.")
        raise typer.Exit(code=1)
    # Copied verbatim, comments and all: the file is meant to be read and edited.
    target.write_text(SEED.joinpath("config.yaml").read_text(encoding="utf8"), encoding="utf8")
    get_config.cache_clear()  # the schema the reset writes through is the one just written
    typer.echo(f"Written: {target}")
    reset()
