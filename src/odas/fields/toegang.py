"""The `toegang` kind: who may open a zaak. Markup in templates/fields/toegang.html."""

from __future__ import annotations

from odas.fields.basic import EmailListField


class ToegangField(EmailListField):
    """The e-mails granted access to one zaak. *This field is the access grant*: a
    type that does not declare one carries no grant, so only the team gets in.
    """

    type, widget = "toegang", "toegang"
    overview = False  # an access rule is not a fact about the case

    def emails(self, value: str) -> set[str]:
        return {e.strip().lower() for e in value.split(",") if e.strip()}
