"""Field kinds: one module per component, `FIELD_TYPES` names them all.

A `type:` in `.app/config.yaml` resolves through the registry below to a class,
and the class carries the behaviour -- validation, serialization, and the name
of its markup in `templates/fields/<widget>.html`. To add a kind, write the
module, add the template, and name it here.
"""

from __future__ import annotations

from odas.fields.base import ROLES, Field, Option, _as_editable, _as_option, _as_options
from odas.fields.basic import (
    BoolField,
    DateField,
    DateTimeField,
    EmailField,
    EmailListField,
    EnumField,
    RefField,
    RefListField,
    StrField,
    StrListField,
    TextField,
)
from odas.fields.flag import FlagField
from odas.fields.latlon import LatLonField
from odas.fields.soort import SoortField
from odas.fields.status import DEFAULT_STATUS, StatusField
from odas.fields.termijn import TermijnField
from odas.fields.toegang import ToegangField
from odas.fields.token import ReplyTokenField, TokenField
from odas.fields.user import UserField
from odas.fields.zaken import ZakenField


def declared_key(fields: dict[str, Field], kind: type[Field]) -> str:
    """The disk key of the first field of this kind, or "" when a type declares none.

    The kind is the promise; the key is the organisation's own word for it. Every
    place that must find a semantic field asks here, so a rename in config.yaml
    never needs a change in the code.
    """
    return next((key for key, f in fields.items() if isinstance(f, kind)), "")


FIELD_TYPES: dict[str, type[Field]] = {
    "str": StrField,
    "text": TextField,
    "email": EmailField,
    "date": DateField,
    "datetime": DateTimeField,
    "latlon": LatLonField,
    "user": UserField,
    "ref": RefField,
    "token": TokenField,
    "reply_token": ReplyTokenField,
    "enum": EnumField,
    "bool": BoolField,
    "flag": FlagField,
    "status": StatusField,
    "termijn": TermijnField,
    "soort": SoortField,
    "toegang": ToegangField,
    "list[email]": EmailListField,
    "list[str]": StrListField,
    "list[ref]": RefListField,
    "zaken": ZakenField,
}

__all__ = [
    "DEFAULT_STATUS",
    "FIELD_TYPES",
    "ROLES",
    "BoolField",
    "DateField",
    "DateTimeField",
    "EmailField",
    "EmailListField",
    "EnumField",
    "Field",
    "FlagField",
    "LatLonField",
    "Option",
    "RefField",
    "RefListField",
    "ReplyTokenField",
    "SoortField",
    "StatusField",
    "StrField",
    "StrListField",
    "TermijnField",
    "TextField",
    "ToegangField",
    "TokenField",
    "UserField",
    "ZakenField",
    "_as_editable",
    "_as_option",
    "_as_options",
    "declared_key",
]
