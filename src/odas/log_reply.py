"""A reply to a mail entry: the new-entry form, addressed as a mail client would."""

from __future__ import annotations

import logging
from email.utils import getaddresses

from odas import users
from odas.zaak import LogEntry, Zaak

log = logging.getLogger(__name__)


def mailable(entry: LogEntry) -> bool:
    """An entry holds an address to answer. A typed note names its writer, not an address."""
    values = [entry.frontmatter.get(k) or "" for k in ("van", "aan", "cc")]
    return any("@" in addr for _, addr in getaddresses(values))


def reply_form(entry: LogEntry) -> dict[str, str]:
    """The form values of the answer. Our own mail goes to its recipients again."""
    fm = entry.frontmatter
    onderwerp = fm.get("onderwerp") or ""
    if not onderwerp.lower().startswith("re:"):
        onderwerp = f"RE: {onderwerp}".strip()
    # The `aan` of a received mail is us, so it is left out.
    aan = fm.get("aan") if entry.direction == "UIT" else fm.get("van")
    return {"aan": aan or "", "cc": fm.get("cc") or "", "onderwerp": onderwerp}


def known_addresses(z: Zaak) -> str:
    """The addresses the send check does not mark: the zaak's own and the team's.

    A directory outage leaves only the zaak's own, so a colleague shows in red.
    """
    own = [z.frontmatter.get(k) or "" for k, f in z.fields.items() if f.type == "email"]
    try:
        team = [u.email for u in users.load_users() if u.is_team]
    except Exception:
        log.warning("Directory unreachable, send check marks every colleague")
        team = []
    return ",".join(sorted({a.strip().lower() for a in own + team if "@" in a}))
