"""The overview columns: which a person may pick, which they picked, how a header orders.

`org.columns` names the columns the table starts with, in the order they stand.
A person picks another set, and the browser keeps it in a cookie: a view
preference is no fact about a case, so it never touches the data dir.
"""

from __future__ import annotations

from urllib.parse import urlencode

from starlette.responses import Response

from odas.appconfig import Field, all_types, org, type_fields

COOKIE = "columns"
ALWAYS = ("id", "titel", "soort")  # the ref and the naam are on every row; soort is a filter
# The narrow flag column stands on every row, so a person cannot switch it off.
# A mark you can hide is no help against a missed message.
FLAGGED = "flag"
FALLBACK = ("aangemaakt", "gewijzigd")  # a config that names no column still lists the dates
DEFAULT_SORT = "gewijzigd"  # where the work just happened is where a person picks it up
YEAR = 365 * 24 * 3600


def _offered() -> dict[str, Field]:
    """Every field a person may show as a column, keyed once, in declaration order.

    A kind that keeps itself off the overview is never on offer.
    """
    found: dict[str, Field] = {}
    for name in all_types():
        for key, f in type_fields(name).items():
            if f.overview and key not in ALWAYS:
                found.setdefault(key, f)
    return found


def defaults() -> dict[str, Field]:
    """The table before a person picks: what `org.columns` names, in that order.

    A name no type declares falls out, so a deleted field breaks no page.
    """
    offered = _offered()
    keys = [k for k in org().columns if k in offered] or [k for k in FALLBACK if k in offered]
    return {k: offered[k] for k in keys}


def candidates() -> dict[str, Field]:
    """Every field on offer, the default columns first: one order rules the page."""
    return {**defaults(), **_offered()}


def chosen(cookie: str) -> dict[str, Field]:
    """The picked columns in the order on offer. A key the config dropped falls out,
    and a choice with nothing left shows the defaults: the table never goes blank."""
    keys = set(cookie.split(","))
    return {k: f for k, f in candidates().items() if k in keys} or defaults()


def headers(params: dict[str, str], sort: str) -> dict[str, tuple[str, str]]:
    """Sort key -> (the address its header opens, the arrow it shows).

    The header that orders the list turns the order round. No order in the
    address means the last-change order, so the Gewijzigd header carries the arrow.
    """
    current = sort or DEFAULT_SORT
    kept = {k: v for k, v in params.items() if v}
    found = {}
    for key in ("ref", FLAGGED, "titel", *candidates()):
        order = f"-{key}" if current == key else key
        arrow = "▲" if current == key else "▼" if current == f"-{key}" else ""
        found[key] = ("/zaken?" + urlencode({**kept, "sort": order}), arrow)
    return found


def same_site(back: str) -> str:
    """A return address: a path on this site, never another host.

    The address rides in the URL, so a mailed link could name any host.
    """
    if back.startswith("/") and not back.startswith("//") and "\\" not in back:
        return back
    return "/zaken"


def remember(response: Response, columns: list[str], secure: bool) -> None:
    response.set_cookie(
        COOKIE, ",".join(columns), max_age=YEAR, httponly=True, samesite="lax", secure=secure
    )
