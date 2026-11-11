"""The settings sections of `$ODAS_DATA_DIR/.app/config.yaml`.

Branding, identity provider, mail relay and server ports are all declared in the
data dir's own config file, so the data dir alone says how the app behaves. The
environment holds one variable, `ODAS_DATA_DIR`, plus the `ODAS_TEST_MODE` dev
bypass. Secrets are never declared here: they live in `.app/secrets.yaml`.

The defaults below are the neutral base for a section a config does not declare.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator


class OrgProfile(BaseModel):
    """Branding and feature flags."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    display_name: str = "ODAS"
    app_title: str = "ODAS"  # browser title / footer name
    favicon: str = ""  # /static path; empty = no favicon
    logo: str = ""  # /static path for the intake page; empty = none
    # The overview columns this organisation starts with, in the order they
    # stand. A person may pick another set; this is what they start from.
    columns: list[str] = []
    # The clock every time a person reads is shown in, and the day a message is filed on.
    timezone: str = "Europe/Amsterdam"

    @field_validator("timezone")
    @classmethod
    def _a_known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone: {value!r}") from None
        return value


class OidcSettings(BaseModel):
    """The identity provider. `client_secret` is a secret and is not declared here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    issuer: str = ""  # empty = sign-in is not configured
    client_id: str = ""
    redirect_uri: str = ""
    group_team: str = "team"  # its members reach every zaak; everyone else per zaak

    @field_validator("issuer")
    @classmethod
    def _no_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


class AiSettings(BaseModel):
    """What the app hands a document to. Declaring the section turns the button on.

    The instruction is the organisation's own words, so what a summary sounds like
    is a matter for the data dir, never for the code. The credential is not here:
    it lives in `.app/secrets.yaml` with the other credentials.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = ""  # the provider's OpenAI-compatible endpoint; empty = OpenAI itself
    model: str = "anthropic/claude-haiku-4.5"
    max_tokens: int = 1024
    timeout: int = 300  # a long document is minutes of work, not seconds
    prompt: str = ""  # what to write about a document, in the organisation's words


class AnalyticsSettings(BaseModel):
    """The visitor counter this data dir sends pageviews to.

    Declaring the section is what turns counting on; a data dir without one
    reaches no other host at all. The website id is public: it is read off the
    page source, so it is a setting and not a credential.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    src: str = ""  # the counter's script, on the host that collects
    website_id: str = ""  # which site the counter files these visits under


class MailTemplate(BaseModel):
    """One message this organisation sends, in its own words.

    `{placeholders}` are filled by the caller. A message with no template here is
    not sent at all: a mail is a declaration like any other capability.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    onderwerp: str
    tekst: str


class SmtpSettings(BaseModel):
    """Mail transport. `smtp_pass` is a secret and is not declared here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = ""  # empty = log only; a folder path = .eml files; a hostname = relay
    port: int = 25
    sender: str = "noreply@localhost"  # the From: header
    user: str = ""  # set it to log in; a relay without STARTTLS is then refused
    footer: str = ""  # offered under a typed message; `{ref}`, `{inzien_url}`, `{zaak_adres}` and `{gebruiker}` are filled
    templates: dict[str, MailTemplate] = {}  # what the app may send, keyed by message name


class MailinSettings(BaseModel):
    """Mail capture: the addresses this instance answers for on port 25.

    A zaak has one address, `<ref>@<domain>`. It carries the zaak and nothing
    else: which way a message went is read off the message. An empty `domains`
    list means this data dir captures no mail at all.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    domains: tuple[str, ...] = ()  # empty = capture is off
    port: int = 2525  # the container maps 25 to it, so the daemon stays unprivileged
    max_bytes: int = 25 * 1024 * 1024


class DemoUser(BaseModel):
    """One person the seeded zaken of a demo name. `name` is "First Last"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    email: str
    team: bool = False


class DemoSettings(BaseModel):
    """A data dir that is open to the public on purpose. Declaring it turns the
    whole demonstration on: nobody signs in, everyone shares one sandbox, and the
    clock empties it.

    `actor` is the identity every request carries, so the audit trail says a
    demonstration did this rather than putting a stranger's edit under a real
    person's name. `users` is the directory: a demo asks pocket-id nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str  # required: a demo with no identity records "onbekend" on every line
    name: str = "Demonstratie"  # what the banner calls this
    reset: str = ""  # what the banner promises; the clock outside does the work
    max_zaken: int = 50
    users: tuple[DemoUser, ...] = ()


class ServerSettings(BaseModel):
    """How the process runs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
