"""The `zaken` kind: what makes a zaak a dossier. Markup in templates/fields/zaken.html."""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator

from odas.fields.base import _as_editable
from odas.fields.basic import RefListField


class ZakenField(RefListField):
    """Refs to other zaken -- what makes a zaak a dossier.

    The picker (`POST /zaken/{ref}/relatie/{key}`) is the only writer, so the
    field is not form-editable: otherwise saving the editor, whose grid does not
    render it, would post an empty value and drop every member.
    """

    type, widget = "zaken", "zaken"
    editable: Annotated[frozenset[str], BeforeValidator(_as_editable)] = frozenset()

    def refs(self, value: str) -> list[str]:
        return [s.strip() for s in value.split(",") if s.strip()]

    def add(self, value: str, ref: str) -> str:
        refs = self.refs(value)
        if ref in refs:
            raise ValueError(f"Zaak {ref} zit al in dit dossier.")
        return ", ".join([*refs, ref])

    def remove(self, value: str, ref: str) -> str:
        return ", ".join(r for r in self.refs(value) if r != ref)
