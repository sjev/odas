"""Logging setup."""

import logging
import os
import platform

LOGGER = "odas"  # every module logs to a child of this one
FMT = "%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"
FALLBACK_LEVEL = "INFO"
SEPARATOR = "*" * 60
SERVER_LOGGER = "uvicorn.error"  # the server's own lines, and a failed request's stack trace


def _level() -> str:
    """`server.log_level`, or INFO while the config is missing or broken.

    Logging must not be what reports a bad config: `dataversion.ensure()` runs
    later and says what is actually wrong.
    """
    from odas.appconfig import server

    try:
        return server().log_level.upper()
    except Exception:
        return FALLBACK_LEVEL


def setup_logging(name: str) -> logging.Logger:
    """Point the `odas` logger at `.app/logs/{name}.log`; level from `server.log_level`.

    `name` is the entry point (`app` or `mail`), not the logger: every module logs
    to a child of `odas`, and each process writes a file of its own.
    """
    from odas.config import Config

    config = Config()
    config.ensure_dirs()  # first writer of .app/ wins; everything after assumes it exists
    log = logging.getLogger(LOGGER)
    server = logging.getLogger(SERVER_LOGGER)
    log.setLevel(_level())
    for old in [*log.handlers, *server.handlers]:
        old.close()
        server.removeHandler(old)  # uvicorn's own handler sits on `uvicorn`, never here
    log.handlers.clear()  # two entry points configure this logger; neither may double the lines
    handler = logging.FileHandler(config.log_file(name))
    handler.setFormatter(logging.Formatter(FMT, DATE_FMT))
    log.addHandler(handler)
    server.addHandler(handler)
    log.propagate = False
    return log


def startup_banner(title: str, facts: dict[str, object]) -> None:
    """Open a run's section in the log: one log file holds many restarts."""
    from odas import __version__
    from odas.config import Config
    from odas.dataversion import DATA_VERSION

    log = logging.getLogger(LOGGER)
    rows = {
        "version": __version__,
        **facts,
        "data dir": Config().root.resolve(),
        "data layout": DATA_VERSION,
        "log level": logging.getLevelName(log.level),
        "python": platform.python_version(),
        "pid": os.getpid(),
    }
    log.info(SEPARATOR)
    log.info(f"ODAS {__version__}: {title}")
    for key, value in rows.items():
        log.info(f"  {key + ':':<13} {value}")
    log.info(SEPARATOR)
    print(f"ODAS {__version__}: {title}")  # the container log is where an operator looks first
