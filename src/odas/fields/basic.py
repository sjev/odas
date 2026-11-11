"""The kinds that are a widget choice and nothing more.

A kind with behaviour of its own gets a module beside this one.
"""

from __future__ import annotations

from odas.fields.base import Field


class StrField(Field):
    pass


class TextField(Field):
    type, widget = "text", "textarea"


class EmailField(Field):
    """One address. The kind owns the check, so a form cannot accept what disk refuses."""

    type, widget = "email", "email"

    def check(self, key: str, fm: dict[str, str]) -> None:
        super().check(key, fm)
        value = (fm.get(key) or "").strip()
        if value and "@" not in value:
            raise ValueError(f"Ongeldig e-mailadres voor '{key}': {value}.")


class DateField(Field):
    type, widget = "date", "date"


class DateTimeField(Field):
    type, widget = "datetime", "datetime"


class RefField(Field):
    type, widget = "ref", "text"


class EnumField(Field):
    type, widget = "enum", "select"


class BoolField(Field):
    """A tick box. `ja` when ticked, empty when not: an unticked box posts nothing."""

    type, widget = "bool", "checkbox"

    def check(self, key: str, fm: dict[str, str]) -> None:
        super().check(key, fm)
        value = (fm.get(key) or "").strip()
        if value not in ("", "ja"):
            raise ValueError(f"Ongeldige waarde voor '{key}': {value}. Kies uit: ja, of leeg.")


class EmailListField(Field):
    type, widget, multi = "list[email]", "email", True


class StrListField(Field):
    type, widget, multi = "list[str]", "text", True


class RefListField(Field):
    type, widget, multi = "list[ref]", "text", True
