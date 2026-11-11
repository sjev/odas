"""The resolved configuration, and the small set of questions the code asks it.

`typeregistry.py` turns the raw `types:` mapping into `Field` objects; this
module holds the result and the accessors. `fields:` is left with only the `log`
section, which is not per-zaak.

It must stay small. A feature that wants a new section is a config seam gap, not
a reason for a second config file.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from odas import configload, typeregistry
from odas.fields import Field, Option
from odas.settings import (
    AiSettings,
    AnalyticsSettings,
    DemoSettings,
    MailinSettings,
    OidcSettings,
    OrgProfile,
    ServerSettings,
    SmtpSettings,
)
from odas.typeregistry import BASE_FIELDS, Fields, TypeRegistry

__all__ = [
    "AppConfig",
    "Field",
    "Option",
    "ai",
    "all_types",
    "analytics",
    "default_type_name",
    "demo",
    "field_for_key",
    "get_config",
    "grouping_type",
    "intake_type",
    "log_fields",
    "mailin",
    "mailin_address",
    "oidc",
    "org",
    "public_fields",
    "server",
    "smtp",
    "type_fields",
    "type_label",
    "type_prefix",
]

# Keys the code itself branches on. Identity lives in the base type specs, and
# the mail keys are filled by the capture daemon, not by the code. What is left
# is the entry name: `log_write` derives the slug from `onderwerp`, so that one
# key must exist.
REQUIRED_KEYS = {"log": ("onderwerp",)}


class AppConfig(BaseModel):
    """Resolved configuration. Frozen: config is an input, never runtime state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 0  # on-disk layout revision; checked by dataversion.ensure()
    org: OrgProfile = OrgProfile()
    oidc: OidcSettings = OidcSettings()
    smtp: SmtpSettings = SmtpSettings()
    mailin: MailinSettings = MailinSettings()
    ai: AiSettings | None = None  # no section = no button and no command
    analytics: AnalyticsSettings | None = None  # no section = nothing is counted
    demo: DemoSettings | None = None  # no section = an ordinary data dir
    server: ServerSettings = ServerSettings()
    fields: dict[str, Fields]
    types: TypeRegistry = {}
    intake_type: str = ""  # derived from `public_intake:`; what the file says is ignored
    prefixes: dict[str, str] = {}  # derived from `prefix:`, one entry per type

    @model_validator(mode="before")
    @classmethod
    def _resolve_the_type_registry(cls, data: Any) -> Any:
        """Apply `extends` and lift `public_intake` before any field is parsed."""
        if not isinstance(data, dict):
            return data
        types, intake, prefixes = typeregistry.resolve(data.get("types") or {})
        fields = dict(data.get("fields") or {})
        fields["log"] = {**typeregistry.BASE_LOG_SPECS, **(fields.get("log") or {})}
        return {
            **data,
            "fields": fields,
            "types": types,
            "intake_type": intake,
            "prefixes": prefixes,
        }

    @model_validator(mode="after")
    def _keeps_keys_the_code_needs(self) -> AppConfig:
        for section, keys in REQUIRED_KEYS.items():
            missing = [k for k in keys if k not in self.fields.get(section, {})]
            if missing:
                raise ValueError(
                    f"fields.{section} is missing required keys: {', '.join(missing)}. "
                    "The code derives the log entry name from it."
                )
        return self


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """The resolved config. Cached: edits to config.yaml need a restart."""
    return AppConfig(**configload.resolve())


def oidc() -> OidcSettings:
    return get_config().oidc


def smtp() -> SmtpSettings:
    return get_config().smtp


def mailin() -> MailinSettings:
    return get_config().mailin


def mailin_address(ref: str) -> str:
    """The address that files a message on this zaak, or "" when capture is off.

    The only place that knows the shape: the daemon parses what this builds.
    """
    config = mailin()
    if not config.domains:
        return ""
    return f"{ref}@{config.domains[0]}"


def ai() -> AiSettings | None:
    """What summaries are made with, or None when this data dir asks for none."""
    return get_config().ai


def analytics() -> AnalyticsSettings | None:
    """The visitor counter this data dir declares, or None when it counts nothing."""
    return get_config().analytics


def demo() -> DemoSettings | None:
    """The demonstration this data dir declares, or None when it is a real one."""
    return get_config().demo


def server() -> ServerSettings:
    return get_config().server


def all_types() -> dict[str, Fields]:
    return get_config().types


def type_fields(name: str) -> dict[str, Field]:
    """The named type's fields; an unknown name yields just the base fields."""
    return get_config().types.get(name, BASE_FIELDS)


def org() -> OrgProfile:
    """Branding, and the columns the overview starts with."""
    return get_config().org


def public_fields(soort: str) -> dict[str, Field]:
    """The fields a public visitor may fill in, in declaration order.

    One role serves both public surfaces: the intake form a stranger submits,
    and the editor an indiener reaches through their token link.
    """
    return {k: f for k, f in type_fields(soort).items() if f.public and "public" in f.editable}


def intake_type() -> str:
    """The soort the public form creates, or "" when no type declares `public_intake`."""
    return get_config().intake_type


def type_prefix(name: str) -> str:
    """The two letters in front of a new ref of this soort."""
    return get_config().prefixes.get(name, typeregistry.DEFAULT_PREFIX)


def default_type_name() -> str:
    """The first declared type, or "" if there are none."""
    return next(iter(get_config().types), "")


def grouping_type() -> str:
    """The soort that groups other zaken, or "" when no type declares one.

    The grouping soort is a declaration, never a name in the code: one data dir
    calls it `dossier` and two others declare nothing of the kind.
    """
    return next(
        (
            name
            for name, fields in all_types().items()
            if any(f.type == "zaken" for f in fields.values())
        ),
        "",
    )


def type_label(name: str) -> str:
    return name.capitalize()


def field_for_key(fields: dict[str, Field], key: str) -> Field | None:
    """Reverse lookup: the field whose `disk_keys(declared_key)` contains `key`."""
    for declared_key, f in fields.items():
        if key in f.disk_keys(declared_key):
            return f
    return None


def log_fields() -> dict[str, Field]:
    return get_config().fields["log"]
