"""The `soort` kind: the type-registry key carried by every zaak."""

from __future__ import annotations

from odas.fields.base import Field


class SoortField(Field):
    """The type-registry key on every zaak: `soort`. Must name a known type."""

    type, widget = "soort", "text"

    def check(self, key: str, fm: dict[str, str]) -> None:
        super().check(key, fm)
        from odas.appconfig import all_types  # one deliberate cycle, confined here

        value = (fm.get(key) or "").strip()
        if value and value not in all_types():
            raise ValueError(f"Onbekend type '{value}' voor '{key}'.")
