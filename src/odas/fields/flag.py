"""The `flag` kind: the work waits for the team. Markup in templates/fields/flag.html."""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator

from odas.fields.base import _as_editable
from odas.fields.basic import BoolField


class FlagField(BoolField):
    """An IN sets it; only a person clears it, with the tick box on the zaak page."""

    type, widget = "flag", "flag"
    overview = False  # the overview draws it in a narrow column of its own
    hint: str = "ja: actie nodig, een IN zet het"
    # The tick box is its one control; the edit form leaves it be.
    editable: Annotated[frozenset[str], BeforeValidator(_as_editable)] = frozenset()
