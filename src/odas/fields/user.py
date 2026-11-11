"""The `user` kind: a team member, picked from pocket-id."""

from __future__ import annotations

from odas.fields.base import Field


class UserField(Field):
    type, widget = "user", "user"
