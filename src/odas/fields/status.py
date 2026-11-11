"""The `status` kind: where a zaak stands. Markup in templates/fields/status.html."""

from __future__ import annotations

from pydantic import model_validator

from odas.fields.base import Option
from odas.fields.basic import EnumField

# The generic vocabulary, used when a config names `status` without listing values.
DEFAULT_STATUS = (
    {"value": "nieuw", "label": "Nieuw", "css": "status-new"},
    {"value": "in_behandeling", "label": "In behandeling", "css": "status-progress"},
    {"value": "wacht", "label": "Wacht", "css": "status-progress"},
    {"value": "afgerond", "label": "Afgerond", "css": "status-done"},
)


class StatusField(EnumField):
    """Where a zaak stands. Owns the badge: the label and css come off its options."""

    type, widget = "status", "status"

    @model_validator(mode="after")
    def _default_options(self) -> StatusField:
        if not self.options:
            object.__setattr__(self, "options", [Option(**o) for o in DEFAULT_STATUS])
        return self

    def badge(self, value: str) -> tuple[str, str]:
        """(label, css class) for a stored value; an unknown value shows as itself."""
        for o in self.options:
            if o.value == value:
                return o.label, o.css
        return value or "—", ""

    def cell(self, z: object, key: str) -> str:
        return self.badge(getattr(z, "frontmatter", {}).get(key, ""))[0]

    def sort_key(self, key: str, fm: dict[str, str]) -> tuple[int, int]:
        """A workflow order, not an alphabet: the declaration decides what comes first."""
        value = (fm.get(key) or "").strip()
        return (0, self.values.index(value)) if value in self.values else (1, 0)
