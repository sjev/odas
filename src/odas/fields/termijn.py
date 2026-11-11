"""The `termijn` kind: a legal deadline. Markup in templates/fields/termijn.html."""

from __future__ import annotations

from datetime import date

from odas.fields.base import Field


class TermijnField(Field):
    """A legal deadline: one field owning two disk keys, a date and its kind.

    Declared as `termijn: termijn`, so `termijn:` itself never reaches disk --
    `disk_keys` replaces it with the pair below. The kind is free text: a person
    names the procedure in their own words.
    """

    type, widget = "termijn", "termijn"
    extra_keys = ("termijn_datum", "termijn_soort")

    def due(self, fm: dict[str, str]) -> str:
        return (fm.get("termijn_datum") or "").strip()

    def kind(self, fm: dict[str, str]) -> str:
        return (fm.get("termijn_soort") or "").strip()

    def days_remaining(self, fm: dict[str, str]) -> int | None:
        """Days until the deadline; None when unset or unparseable."""
        try:
            return (date.fromisoformat(self.due(fm)) - date.today()).days
        except ValueError:
            return None

    def sort_key(self, key: str, fm: dict[str, str]) -> tuple[int, int]:
        """Future/today first (soonest first), then past, then no deadline at all."""
        days = self.days_remaining(fm)
        if days is None:
            return (2, 0)
        return (1, days) if days < 0 else (0, days)

    def check(self, key: str, fm: dict[str, str]) -> None:
        if self.required and not self.due(fm):
            raise ValueError("Veld 'termijn_datum' is verplicht.")

    def comment(self, key: str) -> str:
        return "bv. bezwaar" if key == "termijn_soort" else "JJJJ-MM-DD"

    def cell(self, z: object, key: str) -> str:
        fm = getattr(z, "frontmatter", {})
        due, kind = self.due(fm), self.kind(fm)
        return f"{due} · {kind}" if due and kind else due
