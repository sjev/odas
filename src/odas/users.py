"""User model. Users are sourced from pocket-id (read-only)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class User:
    """One pocket-id account. `is_team` decides blanket access; a zaak's `toegang`
    field decides the rest, so a user outside the team group still belongs here.
    """

    first_name: str
    last_name: str
    email: str
    is_team: bool = False


def load_users() -> list[User]:
    """Every account this data dir knows: pocket-id's, or a demo's own list.

    A demo names its own people, so it has no directory to reach and no outage to
    survive. Every page that lists people reads this, so the seam is here rather
    than in each of them.
    """
    from odas.appconfig import demo
    from odas.config import Config

    declared = demo()
    if declared is not None:
        return [_person(u.name, u.email, u.team) for u in declared.users]
    if Config().test_mode:
        # A local run of a real data dir holds the production key, and that
        # directory refuses a caller it does not know. The dev user is the team.
        return [User(first_name="Test", last_name="User", email="test@example.com", is_team=True)]

    from odas import pocketid  # lazy: avoids import cycle with pocketid

    return pocketid.list_users()


def _person(name: str, email: str, is_team: bool) -> User:
    """Split a declared "First Last" into the two halves the directory hands over."""
    first, _, last = name.strip().partition(" ")
    return User(first_name=first, last_name=last, email=email, is_team=is_team)


def display_name(email: str) -> str:
    """The name the directory holds for this address, or the address itself.

    A directory outage must not stop a message going out, so an unanswerable
    lookup falls back to the address rather than raising.
    """
    target = (email or "").strip().lower()
    if not target:
        return ""
    try:
        people = load_users()
    except Exception:
        return email
    for u in people:
        if u.email.lower() == target:
            return f"{u.first_name} {u.last_name}".strip() or u.email
    return email


def is_team(email: str) -> bool:
    """Whether this address is in the team group, as the directory says right now.

    Raises whatever the directory read raises. An unanswerable question must not
    come back as "no": that would read as a revoked grant rather than an outage.
    """
    found = account(email)
    return found is not None and found.is_team


def account(email: str) -> User | None:
    """The directory's account for this address right now, or None when it has none.

    Raises whatever the directory read raises, for the reason `is_team` gives.
    """
    target = (email or "").strip().lower()
    if not target:
        return None  # an empty identity is no account, and needs no lookup
    return next((u for u in load_users() if u.email.lower() == target), None)
