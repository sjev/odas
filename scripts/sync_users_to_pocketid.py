#!/usr/bin/env python3
"""One-time migration: upload data/users.jsonl into pocket-id.

Creates missing users and puts the `intake-team` rows in the team group. Everyone
else is created without a group: they reach a zaak through its `toegang` field, not
through membership. Idempotent: re-running only updates group membership. Dry run by
default; pass --apply to write.

Reads the data dir like the app does: `ODAS_DATA_DIR/.app/config.yaml` for the
issuer and the group names, `.app/secrets.yaml` for the admin key.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

TEAM_ROLE = "intake-team"  # the users.jsonl value that means "in the team group"


def _team_group() -> str:
    from odas.appconfig import oidc

    return oidc().group_team


def _client(base: str, api_key: str) -> httpx.Client:
    return httpx.Client(base_url=base.rstrip("/"), headers={"X-API-KEY": api_key}, timeout=15)


def _resolve_group_ids(client: httpx.Client) -> dict[str, str]:
    """Map wanted group names → pocket-id group ids; abort if any is missing."""
    page, by_name = 1, {}
    while True:
        r = client.get(
            "/api/user-groups", params={"pagination[page]": page, "pagination[limit]": 100}
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        for g in data:
            by_name[g.get("name")] = g.get("id")
        if len(data) < 100:
            break
        page += 1
    ids = {}
    for name in {_team_group()}:
        gid = by_name.get(name)
        if gid is None:
            sys.exit(
                f"ERROR: group {name!r} not found in pocket-id. Create it first in the admin UI."
            )
        ids[name] = gid
    return ids


def _find_user(client: httpx.Client, email: str) -> dict[str, object] | None:
    r = client.get("/api/users", params={"search": email, "pagination[limit]": 100})
    r.raise_for_status()
    for u in r.json().get("data", []):
        if u.get("email", "").lower() == email.lower():
            return dict(u)
    return None


def _username(email: str) -> str:
    return "".join(c if (c.isalnum() or c in "._-") else "." for c in email.lower())


def sync(users_file: Path, base: str, api_key: str, dry_run: bool) -> None:
    rows = [
        json.loads(line)
        for line in users_file.read_text(encoding="utf8").splitlines()
        if line.strip()
    ]
    with _client(base, api_key) as client:
        group_ids = _resolve_group_ids(client)
        for row in rows:
            email = row["email"].strip()
            role = row["role"].strip()
            group_name = _team_group() if role == TEAM_ROLE else ""
            gids = [group_ids[group_name]] if group_name else []
            existing = _find_user(client, email)

            if dry_run:
                action = "update" if existing else "create"
                print(f"  [dry] {action} {email} → group {group_name or '(none)'}")
                continue

            display_name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()

            if existing:
                uid = existing["id"]
                r = client.put(
                    f"/api/users/{uid}",
                    json={
                        "username": existing["username"],
                        "email": existing.get("email") or email,
                        "emailVerified": existing.get("emailVerified", True),
                        "firstName": row.get("first_name", ""),
                        "lastName": row.get("last_name", ""),
                        "displayName": display_name,
                        "isAdmin": existing.get("isAdmin", False),
                        "disabled": existing.get("disabled", False),
                    },
                )
                r.raise_for_status()
                print(f"  update {email} → group {group_name or '(none)'}")
            else:
                resp = client.post(
                    "/api/users",
                    json={
                        "username": _username(email),
                        "email": email,
                        "emailVerified": True,
                        "firstName": row.get("first_name", ""),
                        "lastName": row.get("last_name", ""),
                        "displayName": display_name,
                        "isAdmin": False,
                        "disabled": False,
                    },
                )
                if not resp.is_success:
                    print(f"  skip   {email}: {resp.status_code} {resp.text}", file=sys.stderr)
                    continue
                uid = resp.json()["id"]
                print(f"  create {email} → group {group_name or '(none)'}")

            r = client.put(f"/api/users/{uid}/user-groups", json={"userGroupIds": gids})
            r.raise_for_status()


if __name__ == "__main__":
    from odas import appsecrets
    from odas.appconfig import oidc
    from odas.config import Config

    dry = "--apply" not in sys.argv
    api_key = appsecrets.require("pocket_id_api_key")
    base = oidc().issuer or sys.exit("ERROR: no `oidc.issuer` in the data dir's config.yaml")
    users_file = Config().users_file
    if not users_file.exists():
        sys.exit(f"ERROR: {users_file} not found")

    print("Dry run — pass --apply to write.\n" if dry else "Applying to pocket-id.\n")
    sync(users_file, base, api_key, dry_run=dry)
    print("\nDone.")
