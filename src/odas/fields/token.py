"""The token kinds, including the capability token behind /inzien-<token>."""

from __future__ import annotations

import secrets
from typing import Annotated

from pydantic import BeforeValidator

from odas.fields.base import Field, _as_editable


class TokenField(Field):
    type, widget = "token", "text"
    overview = False  # a capability token is not read off a list of cases


class ReplyTokenField(TokenField):
    """The capability token behind /inzien-<token>.

    Minted at creation, never edited, and never written into the frontmatter: the
    value lives in `.access-token` beside `index.md`. A type declares this field
    to say it is shareable by link; the declaration is all that is on disk here.
    """

    type = "reply_token"
    ondisk = False
    editable: Annotated[frozenset[str], BeforeValidator(_as_editable)] = frozenset()

    @staticmethod
    def mint() -> str:
        return secrets.token_urlsafe(16)
