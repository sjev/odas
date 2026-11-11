"""Who may open a zaak, and who is writing.

One rule, stated once: the team group opens every zaak, and a zaak's `toegang`
field opens that one. There is no third answer and no read-only tier -- whoever
gets in may edit. Read-only sharing is the token link, which needs no account.

Nothing here takes a `Request`, so a test states a rule without going through
HTTP. `of()` is the one adapter, and the routes turn the answer into a status
code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from odas import zaak
from odas.fields import ZakenField
from odas.zaak import Zaak


@dataclass(frozen=True)
class Viewer:
    """Who is asking. `email` is the identity the grant and the audit both read."""

    email: str = ""
    is_team: bool = False


def of(request: Request) -> Viewer:
    """The viewer the middleware put on this request."""
    return Viewer(
        email=(getattr(request.state, "email", "") or "").lower(),
        is_team=bool(getattr(request.state, "is_team", False)),
    )


def may_access(v: Viewer, z: Zaak) -> bool:
    """Read and write are one permission: the grant is not a read-only tier."""
    return v.is_team or (bool(v.email) and v.email in z.toegang)


def may_open(v: Viewer, ref: str) -> bool:
    """Whether this ref names a zaak this viewer may open. Absent and ungranted read alike."""
    folder = zaak.find(ref)
    return folder is not None and may_access(v, zaak.load_safe(folder))


def unopenable_member(v: Viewer, before: Zaak, after: dict[str, str]) -> str:
    """The first ref an edit adds to a `zaken` field that this viewer may not open.

    A dossier shows its members, so grouping a zaak would hand its fields to
    whoever can open the dossier. "" when every new member is one they may open.
    """

    def members(z: Zaak) -> set[str]:
        return {
            ref
            for key, f in z.fields.items()
            if isinstance(f, ZakenField)
            for ref in f.refs(z.frontmatter.get(key, ""))
        }

    # The fields of the soort the edit leaves behind, since a raw edit may change it.
    soort = after.get("soort") or before.soort
    edited = Zaak(id=before.id, ref=before.ref, frontmatter=after, body="", soort=soort)
    added = members(edited) - members(before)
    return next((ref for ref in sorted(added) if not may_open(v, ref)), "")


def create_refusal(v: Viewer) -> str:
    """Why this viewer may not start a zaak, in Dutch, or "" when they may.

    A demonstration adds a ceiling to the team rule: everyone who visits is the
    team there, so without one a single stranger fills it with folders between
    resets. The two refusals are different facts, so they read differently.
    """
    from odas.appconfig import demo

    declared = demo()
    if declared is not None and len(zaak.list_ids()) >= declared.max_zaken:
        return "Deze demonstratie zit vol. Na de volgende reset is er weer ruimte."
    return "" if v.is_team else "Alleen teamleden hebben toegang."


def may_create(v: Viewer) -> bool:
    """A new zaak belongs to the organisation, so only the team starts one."""
    return not create_refusal(v)


def open_zaak(v: Viewer, ref: str) -> tuple[Path, Zaak]:
    """The zaak this viewer may read, and the folder it lies in. A zaak without a
    grant is as absent as one that does not exist: the number of zaken we hold is
    not theirs to learn."""
    folder = zaak.find(ref)
    if folder is None or not may_access(v, zaak.load_safe(folder)):
        raise LookupError(f"Zaak niet gevonden: {ref}")
    return folder, zaak.load(folder)


def actor(v: Viewer) -> str:
    """The name `audit.log` records: the same identity the access rule reads."""
    return v.email or "onbekend"
