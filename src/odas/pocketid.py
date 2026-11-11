"""Read team users from pocket-id (the single source of truth)."""

from __future__ import annotations

import logging

import httpx2 as httpx

from odas import appsecrets
from odas.appconfig import oidc
from odas.users import User

log = logging.getLogger(__name__)

_PAGE_LIMIT = 100


def _is_team(group_names: set[str]) -> bool:
    return oidc().group_team in group_names


def _fetch_users() -> list[User]:
    cfg = oidc()
    api_key = appsecrets.get_secrets().pocket_id_api_key
    if not cfg.issuer or not api_key:
        # This data dir declares no directory. That is a state, not a failure:
        # there is nobody to list, and so nobody is in the team group. An outage
        # is the other case entirely, and it raises.
        log.debug("No pocket-id directory is configured for this data dir")
        return []
    headers = {"X-API-KEY": api_key}
    out: list[User] = []
    page = 1
    with httpx.Client(base_url=cfg.issuer, headers=headers, timeout=10) as client:
        while True:
            r = client.get(
                "/api/users",
                params={"pagination[page]": page, "pagination[limit]": _PAGE_LIMIT},
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            for u in data:
                # pocket-id sends the key with a null value, so a default is not enough.
                email = (u.get("email") or "").strip()
                if not email:
                    continue  # no address means no identity: this account is not listed
                groups = {g.get("name") for g in u.get("userGroups", [])}
                out.append(
                    User(
                        first_name=u.get("firstName") or "",
                        last_name=u.get("lastName") or "",
                        email=email,
                        is_team=_is_team(groups),
                    )
                )
            if len(data) < _PAGE_LIMIT:
                break
            page += 1
    return out


def list_users() -> list[User]:
    """Every pocket-id account, fetched fresh on every call.

    A read that fails raises. There is deliberately no fallback to an earlier
    list: on the page a stale directory looks exactly like a current one, so the
    caller is told instead of being left to wonder.
    """
    users = _fetch_users()
    log.debug(f"Pocket-ID users: fetched {len(users)} users")
    return users
