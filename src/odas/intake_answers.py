"""What an intake submission holds, and what blocks it.

The builtin form posts fields; a data dir's own page posts one JSON part. Both
arrive here as one flat dict, so one set of rules binds them.
"""

from __future__ import annotations

import json

from odas import schema
from odas.appconfig import Field
from odas.fields import EmailField

TITEL = "titel"
OMSCHRIJVING = "omschrijving"
REQUIRED = "Dit veld is verplicht."
TITEL_MAX = 150  # a name for lists and mail; the story goes in the omschrijving
TOO_LONG = f"Maximaal {TITEL_MAX} tekens. Zet de details in de omschrijving."


def email_key(fields: dict[str, Field]) -> str:
    """The key holding the address the confirmation goes to; "" if the type asks for none."""
    return next((k for k, f in fields.items() if isinstance(f, EmailField)), "")


def from_json(part: str) -> dict[str, str]:
    """The answers of a data dir's own page, flat, as the builtin form posts them."""
    try:
        data = json.loads(part)
        flat = {**data.get("velden", {}), TITEL: data.get(TITEL), OMSCHRIJVING: data["body"]}
        return {k: _text(v) for k, v in flat.items()}
    except (ValueError, AttributeError, KeyError, TypeError):
        raise ValueError("Het formulier stuurde geen leesbare gegevens.") from None


def _text(value: object) -> str:
    """An answer is text; null is an empty answer. Anything else would land as its repr."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(value)
    return value


def check(values: dict[str, str], fields: dict[str, Field]) -> dict[str, str]:
    """A Dutch message per key that blocks this submission; empty when it may go on."""
    # Three things are required whatever the type says: a name for the zaak, a
    # description, and the address the confirmation goes to. A submission nobody
    # can answer is not a submission. `required:` in the config is a schema rule
    # that binds every writer, including the team, so it is not the same thing.
    structural = [TITEL, OMSCHRIJVING, *(k for k in [email_key(fields)] if k)]
    errors = {k: REQUIRED for k in structural if not values.get(k, "")}
    errors.update(
        {k: REQUIRED for k, f in fields.items() if f.required_for("public") and not values.get(k)}
    )
    if len(values.get(TITEL, "")) > TITEL_MAX:
        errors[TITEL] = TOO_LONG
    if errors:
        return errors
    try:  # the field kinds own their checks, so the form cannot disagree with disk
        schema.validate({k: v for k, v in values.items() if k != OMSCHRIJVING}, fields)
    except ValueError as e:
        return {"_": str(e)}
    return {}
