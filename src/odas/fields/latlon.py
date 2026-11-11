"""The `latlon` kind: a place. Markup and map dialog in templates/fields/latlon.html."""

from __future__ import annotations

import re

from odas.fields.base import Field

_AXIS = r"""(\d+(?:\.\d+)?)°\s*(?:(\d+(?:\.\d+)?)'\s*)?(?:(\d+(?:\.\d+)?)"\s*)?"""
# Degrees, minutes, seconds as Google Maps copies them: 51°27'27.9"N 5°38'54.1"E
_DMS = re.compile(rf"{_AXIS}([NS])[\s,]*{_AXIS}([EW])")


def _decimal(value: str) -> tuple[float, float] | None:
    parts = value.split(",")
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _dms(value: str) -> tuple[float, float] | None:
    m = _DMS.fullmatch(value.strip())
    if not m:
        return None
    g = m.groups()

    def axis(d: str, mi: str | None, s: str | None, hemi: str) -> float:
        v = float(d) + float(mi or 0) / 60 + float(s or 0) / 3600
        return -v if hemi in "SW" else v

    return axis(*g[:4]), axis(*g[4:])


class LatLonField(Field):
    """A location, held as free text, as `lat,lon`, or in degrees as Google Maps gives it.

    Free text stays legal -- an intake often names a street before anyone has
    pinned it -- so only a value `coords` can parse gets a map. The value on
    disk stays as typed; the map reads `point`.
    """

    type, widget = "latlon", "latlon"

    def coords(self, value: str) -> tuple[float, float] | None:
        """(lat, lon) of a pinned location; None when the value is free text."""
        found = _decimal(value or "") or _dms(value or "")
        if not found:
            return None
        lat, lon = found
        return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None

    def point(self, value: str) -> str:
        """`lat,lon` in decimals for the map; "" when the value is free text."""
        c = self.coords(value)
        return f"{round(c[0], 6)},{round(c[1], 6)}" if c else ""
