"""The overview list: which zaken a viewer sees, narrowed how, in what order.

The read side of the application interface. The overview page renders whatever
these return, so scope, narrowing and ordering are decided here and not in a
template. One folder scan feeds a request: `visible` reads the store, and the
other two cut the list it returns. Neither needs an index.

Narrowing finds a known item or filters a facet over frontmatter the app already
parses.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from datetime import datetime
from typing import Any

from odas import access, zaak, zaak_columns
from odas.appconfig import Field, all_types, type_fields, type_label
from odas.fields import RefField, RefListField


def _newest_first(when: datetime | None) -> tuple[int, float]:
    """Newest first. A zaak without the stamp comes last."""
    return (0, -when.timestamp()) if when else (1, 0.0)


# The orders every soort offers, whatever it declares. Every other order is a
# field a person may show as a column. Each key leads with 0 for a value, 1 or
# more for none, so a turned-round order can keep the empty ones last.
BASE_SORTS: dict[str, Callable[[zaak.Zaak], Any]] = {
    "aangemaakt": lambda z: _newest_first(z.created),
    "gewijzigd": lambda z: _newest_first(z.modified),
    "ref": lambda z: (0, z.ref),
    "titel": lambda z: (0, z.titel.casefold()),
    # Both groups carry a value, so a second click turns this order round as well.
    zaak_columns.FLAGGED: lambda z: (0, 0 if z.flagged else 1),
}
REF_KEYS = ("zaak", "ref")  # what a person calls the ref in the box
OVERIG = "overig"  # the entry for a soort the config no longer declares
TERMIJN, STATUS = "termijn", "status"  # the two kinds this page treats specially


def terms(q: str) -> list[str]:
    """Split the box into terms. Quotes hold a phrase together.

    Public because the wetten box speaks the same grammar: a person learns one
    box, not two.
    """
    try:
        split = [t for t in shlex.split(q) if t]
    except ValueError:  # an unclosed quote, while a person is still typing
        split = [t for t in q.replace('"', " ").replace("'", " ").split() if t]
    found: list[str] = []
    for t in split:  # `status: nieuw` is one term: the space after the colon is habit
        if found and found[-1].endswith(":"):
            found[-1] += t
        else:
            found.append(t)
    return found


def _matches(z: zaak.Zaak, term: str) -> bool:
    """One term against one zaak. A `sleutel:waarde` term names a key on disk."""
    key, _, value = term.partition(":")
    key, value = key.casefold(), value.casefold()
    if value and key in REF_KEYS:
        return value in z.ref.casefold()
    if value and key in z.frontmatter:
        return value in str(z.frontmatter.get(key) or "").casefold()
    needle = term.casefold()
    return any(needle in h.casefold() for h in (z.ref, z.titel, z.id, *_values(z)))


def _values(z: zaak.Zaak) -> list[str]:
    """What a plain word also searches: a person knows the value, not its key.

    Not a secret or an access list, which the overview never shows. Not a ref
    to another zaak: a search for a ref finds that zaak, not its dossier.
    """
    return [
        str(z.frontmatter.get(key) or "")
        for key, f in type_fields(z.soort).items()
        if f.overview and not isinstance(f, RefField | RefListField)
    ]


def _kind(kind: str) -> tuple[str, Field] | None:
    """The first field of this kind any type declares: its disk key and declaration."""
    for name in all_types():
        for key, f in type_fields(name).items():
            if f.type == kind:
                return key, f
    return None


def status_options() -> list[tuple[str, str]]:
    """(value, label) per status the organisation declared; empty when it declares none."""
    found: dict[str, str] = {}
    for name in all_types():
        for f in type_fields(name).values():
            if f.type == STATUS:
                found.update({o.value: o.label for o in f.options})
    return list(found.items())


def _order(sort: str) -> Callable[[zaak.Zaak], Any]:
    """What the list is ordered on. Anything else falls back to the last change: a
    hand-typed address must never produce an error page."""
    if sort in BASE_SORTS:
        return BASE_SORTS[sort]
    f = zaak_columns.candidates().get(sort)
    if f is None:
        return BASE_SORTS[zaak_columns.DEFAULT_SORT]
    return lambda z: f.sort_key(sort, z.frontmatter)


def visible(v: access.Viewer, q: str = "", status: str = "", sort: str = "") -> list[zaak.Zaak]:
    """The zaken this viewer may open, narrowed and ordered.

    Access comes first, always: a term can never widen what a person sees. The
    status choice is one more term, so the box and the dropdown narrow by one rule.
    """
    zaken = [z for z in zaak.list_all() if access.may_access(v, z)]
    return narrow(zaken, q=q, status=status, sort=sort)


def narrow(
    zaken: list[zaak.Zaak], q: str = "", status: str = "", sort: str = ""
) -> list[zaak.Zaak]:
    """Cut an already-scanned, access-filtered list by the box, the status and the order.

    Split out of `visible` so one page can narrow the same scan twice: once for
    the rows, once more loosely for what a choice offers. One folder scan still
    feeds the request.
    """
    found = terms(q)
    declared = _kind(STATUS)
    if status and declared:
        found.append(f"{declared[0]}:{status}")
    for term in found:
        zaken = [z for z in zaken if _matches(z, term)]
    order = _order(sort.removeprefix("-"))
    zaken.sort(key=order, reverse=sort.startswith("-"))
    zaken.sort(key=lambda z: order(z)[0])  # stable: a zaak without a value stays last
    return zaken


def of_soort(zaken: list[zaak.Zaak], soort: str) -> list[zaak.Zaak]:
    """One page's rows. Empty is every soort; `overig` is every retired one."""
    if not soort:
        return zaken
    if soort == OVERIG and soort not in all_types():
        return [z for z in zaken if z.soort not in all_types()]
    return [z for z in zaken if z.soort == soort]


def soort_counts(zaken: list[zaak.Zaak], chosen: str = "") -> list[tuple[str, str, int]]:
    """(soort, label, count) per soort that has zaken: the entries on offer.

    Takes an already-narrowed list, so the counts follow the box and one folder
    scan feeds both the rows and the entries. A soort the config no longer
    declares gets a trailing "Overig": data outlives the schema that made it.
    The soort a person picked stays on the list at zero, so a narrowing that
    empties it never traps them inside it.
    """
    counts = [(name, type_label(name), len(of_soort(zaken, name))) for name in all_types()]
    orphans = [z for z in zaken if z.soort not in all_types()]
    if orphans or chosen == OVERIG:
        counts.append((OVERIG, type_label(OVERIG), len(orphans)))
    return [c for c in counts if c[2] or c[0] == chosen]
