"""The clock of the org: `org.timezone`, whatever zone the server runs in.

A stamp on disk is UTC. A stamp without a zone was written before that, on the
clock of the org, and is read as such.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from odas.appconfig import get_config


def zone() -> ZoneInfo:
    return ZoneInfo(get_config().org.timezone)


def now() -> datetime:
    return datetime.now(zone()).replace(microsecond=0)


def local(moment: datetime) -> datetime:
    """The moment on the clock of the org. A stamp without a zone was already on it."""
    return moment.replace(tzinfo=zone()) if moment.tzinfo is None else moment.astimezone(zone())


def stamp(moment: datetime | None = None) -> str:
    """The moment in UTC, ISO to the second: the disk holds one clock, the page shows the org's."""
    return (moment or now()).astimezone(UTC).isoformat(timespec="seconds")
