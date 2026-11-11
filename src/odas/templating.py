"""Shared Jinja2 environment (filters, globals) for all route modules."""

from __future__ import annotations

from email.utils import parseaddr
from pathlib import Path

import markdown as _md
import nh3
from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from odas import __version__, zaak_columns
from odas.appconfig import analytics, demo, log_fields
from odas.config import Config
from odas.fields import Field
from odas.log_reply import mailable
from odas.settings import AnalyticsSettings
from odas.wetten_read import has_wetten
from odas.zaak import fmt_date

_BASE_DIR = Path(__file__).resolve().parent


def log_form_fields() -> dict[str, Field]:
    """The log fields a person may type. The rest is read off a received message."""
    return {k: f for k, f in log_fields().items() if "team" in f.editable}


MAIL_KEYS = ("aan", "cc")


def log_mail_fields() -> dict[str, Field]:
    """The recipients, when this data dir lets a person type them. Empty = no sending."""
    return {k: f for k, f in log_form_fields().items() if k in MAIL_KEYS}


Section = tuple[str, list[tuple[str, Field]]]


def form_sections(
    fields: dict[str, Field],
    role: str,
    skip: list[str] | None = None,
    locked: list[str] | None = None,
) -> tuple[list[tuple[str, Field]], list[Section]]:
    """(facts, sections) for a form: what the role may not edit, then what it may.

    Editable fields that share a `group` stand together, at the place the group
    first appears in the declaration. A field without one is a section of its own.
    `locked` names fields this one page may not edit, whatever the declaration says.
    """
    facts, sections = [], []
    by_group: dict[str, Section] = {}
    for key, f in fields.items():
        if key in (skip or []):
            continue
        if role not in f.editable or key in (locked or []):
            facts.append((key, f))
        elif not f.group:
            sections.append(("", [(key, f)]))
        elif f.group in by_group:
            by_group[f.group][1].append((key, f))
        else:
            by_group[f.group] = (f.group, [(key, f)])
            sections.append(by_group[f.group])
    return facts, sections


def _analytics_for(request: Request) -> AnalyticsSettings | None:
    """The counter for this page, or None when this page must not be counted.

    A counter files the path it loaded on. `/inzien-{token}` carries the key that
    opens a zaak, so tagging that page would put the key in the counter's own
    database. The indiener's pages are therefore never counted.
    """
    if request.url.path.startswith("/inzien-"):
        return None
    return analytics()


def _org_context(request: Request) -> dict[str, object]:
    """Expose the active org profile to every template, resolved per request.

    `demo` rides along: the banner belongs on every page, so no route carries it.
    `analytics` likewise, and it is the only value here that a page may refuse.
    """
    return {"org": Config().org, "demo": demo(), "analytics": _analytics_for(request)}


def addr_name(value: str) -> str:
    """The name out of `Naam <adres>`; the value itself when it carries none.

    A person reads a name. The address stays on disk, where a grep finds it.
    """
    name, addr = parseaddr(value or "")
    return name or addr or value


templates = Jinja2Templates(
    directory=str(_BASE_DIR / "templates"), context_processors=[_org_context]
)
templates.env.globals["version"] = __version__
# Callables, not values: an imported macro bypasses context processors, and the
# log form must follow whatever `fields.log` declares for this data dir.
templates.env.globals["log_fields"] = log_fields
templates.env.globals["log_form_fields"] = log_form_fields
templates.env.globals["log_mail_fields"] = log_mail_fields
templates.env.globals["form_sections"] = form_sections
# The table falls back to the config's columns, so a dossier's members need no
# route to pass them; the overview passes the columns a person picked.
templates.env.globals["default_columns"] = zaak_columns.defaults
# A row carries the list it came from, so the back link restores the filter and
# the order. The address is untrusted input; this holds it on this site.
templates.env.globals["same_site"] = zaak_columns.same_site
# The `wetten/` folder is the declaration, so the menu entry follows the disk and
# not a flag. A callable: a law can be fetched long after the app started.
templates.env.globals["has_wetten"] = has_wetten
# A callable, not a dict: imported macros bypass context processors, and the
# badge table now follows the configured schema rather than an import-time copy.
templates.env.filters["dt"] = fmt_date
templates.env.filters["naam"] = addr_name
templates.env.filters["mailable"] = mailable
# nh3 strips raw HTML that python-markdown passes through unchanged; zaak and
# log bodies carry unauthenticated indiener input, so this guards against XSS.
# A link opens a new tab, so a reader who checks a source keeps the zaak page.
templates.env.filters["md"] = lambda text: Markup(
    nh3.clean(
        _md.markdown(text or "", extensions=["nl2br", "tables"]),
        set_tag_attribute_values={"a": {"target": "_blank"}},
    )
)
