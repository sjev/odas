"""Template context for the zaak page: the read view, the public view, the editor.

Access checks and request plumbing stay in `web_helpers`; this module only turns a
folder into a dict the templates can render.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import Request

from odas import access, ai, appconfig, documents, handleiding, log_reply, schema, users, zaak
from odas.fields import ToegangField, ZakenField, declared_key

__all__ = ["edit_context", "public_view", "relation_zaken", "zaak_context", "zaak_label"]


def public_view(z: zaak.Zaak) -> zaak.Zaak:
    """Indiener-safe copy: no internal notes, no audit history."""
    return zaak.Zaak(
        id=z.id,
        ref=z.ref,
        frontmatter=z.frontmatter,
        body=z.body,
        soort=z.soort,
        history="",
        log_entries=[e for e in z.log_entries if e.direction != "LOG"],
        token="",  # the page needs the link; the record handed to the template does not
    )


def edit_context(z: zaak.Zaak, v: access.Viewer) -> dict[str, object]:
    """Behandelaar/toegang dropdown data plus the relation picker, for the editor."""
    all_users = users.load_users()
    selected = z.toegang
    known = {u.email.lower() for u in all_users}
    return {
        "behandelaars": [u for u in all_users if u.is_team],
        "grantees": all_users,  # anyone with an account may be granted one zaak
        # The dialog posts under the key this soort declares, never under "toegang".
        "toegang_key": declared_key(z.fields, ToegangField),
        "selected": selected,
        "extra_grantees": sorted(selected - known),  # granted, but not in the directory
        "relation_key": relation_key(z),
        "relation_zaken": relation_zaken(z),
        "relation_opties": relation_opties(z, v),
        "add_error": None,
        "add_value": "",
    }


def relation_key(z: zaak.Zaak) -> str:
    """The declared key of this zaak's ZakenField, or "" when it has none."""
    return next((key for key, f in z.fields.items() if isinstance(f, ZakenField)), "")


def relation_zaken(z: zaak.Zaak) -> list[zaak.Zaak]:
    """The zaken this one groups, loaded; an unresolvable ref becomes an error row."""
    key = relation_key(z)
    if not key:
        return []
    field = z.fields[key]
    assert isinstance(field, ZakenField)
    out: list[zaak.Zaak] = []
    for ref in field.refs(z.frontmatter.get(key, "")):
        folder = zaak.find(ref)
        if folder is None:
            out.append(zaak.Zaak(id=ref, ref=ref, frontmatter={}, body="", error="Onbekende zaak."))
        else:
            out.append(zaak.load_safe(folder))
    return out


def relation_opties(z: zaak.Zaak, v: access.Viewer) -> list[tuple[str, str]]:
    """(ref, label) for every zaak this viewer could still add, newest first."""
    key = relation_key(z)
    if not key:
        return []
    linked = {m.ref for m in relation_zaken(z)} | {z.ref}
    others = [
        o
        for o in zaak.list_all()
        if o.ref not in linked and not relation_key(o) and access.may_access(v, o)
    ]
    others.sort(key=lambda o: o.created or datetime.min.replace(tzinfo=UTC), reverse=True)
    return [(o.ref, zaak_label(o)) for o in others]


def zaak_label(z: zaak.Zaak) -> str:
    badge = z.badge
    return f"{z.titel} · {badge[0]}" if badge else z.titel


def mail_footer(ref: str, inzien_url: str, gebruiker: str) -> str:
    """The closing line this data dir offers under a typed message, or "" for none.

    The writer signs it, so the name is the reader's own, not the organisation's.
    """
    text = appconfig.smtp().footer
    if not text:
        return ""
    return text.format(
        ref=ref,
        inzien_url=inzien_url,
        zaak_adres=appconfig.mailin_address(ref),
        gebruiker=gebruiker,
    )


def zaak_context(
    request: Request, folder: Path, public: bool = False, **extra: object
) -> dict[str, object]:
    """Build zaak template context; the indiener gets a filtered view + reply form."""
    base = str(request.base_url).rstrip("/")
    z = zaak.load(folder)
    token = z.token
    members = relation_zaken(z)
    if public:
        z = public_view(z)
    # Read off the view, so the indiener never gets a document of an internal note.
    docs = documents.documents_of(folder, z)
    ctx: dict[str, object] = {
        "zaak": z,
        "token": token,
        # Every file address on the page hangs off this: the indiener holds a
        # token, not an account, so a team address would send them to the login.
        "base_url": f"/inzien-{token}" if public else f"/zaken/{z.ref}",
        "inzien_url": f"{base}/inzien-{token}" if token else "",
        # Bcc it when sending, forward an incoming letter to it. One address.
        "mail_adres": "" if public else appconfig.mailin_address(z.ref),
        # The manual's own words, beside the address, because Cc and Bcc get mixed up.
        "mail_help": handleiding.section("Zelf verstuurde of ontvangen e-mail"),
        "readonly": public,
        # The gathered list is the team's page; the indiener reads the logboek.
        "documenten": [] if public else docs,
        "log_documenten": documents.by_entry(docs),
        # The indiener reads a summary, and never pays for one.
        "ai": not public and ai.configured(),
        "reply": public,
        "log_fm": {},
        "log_body": "",
        "log_direction": "LOG",
        "log_date": date.today().isoformat(),
        "log_error": None,
        "log_footer": ""
        if public
        else mail_footer(
            z.ref,
            f"{base}/inzien-{token}" if token else "",
            users.display_name(access.actor(access.of(request))),
        ),
        "log_known": "" if public else log_reply.known_addresses(z),
        "fields": z.fields,
        # The indiener sees declared public fields only; the team sees the file.
        "extra_fm": {} if public else schema.undeclared(z.frontmatter, z.fields),
        "relation_key": relation_key(z),
        "relation_zaken": members,
        "relation_locaties": "; ".join(m.point for m in members if m.point),
        "relation_inzien_urls": {
            m.ref: f"{base}/inzien-{m.token}" for m in members if public and m.token
        },
    }
    ctx.update(extra)
    values = ctx.get("values")
    if isinstance(values, dict):
        ctx["values"] = {"naam": z.frontmatter.get("contact_naam", ""), **values}
    return ctx
