"""The contract every field kind implements.

`appconfig.py` expands YAML shorthand and instantiates the right class;
`schema.py` reads `Field` instances to serialize and validate frontmatter.
Each kind lives in its own module beside this one; see `__init__.py`.
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator

# The two audiences a field may be editable by. "team" is the internal side:
# anyone the access rule lets in, whether through the team group or a toegang grant.
ROLES = frozenset({"team", "public"})


def _as_option(value: Any) -> Any:
    if isinstance(value, str):
        return {"value": value, "label": value}
    if isinstance(value, dict) and not value.get("label"):
        return {**value, "label": value.get("value", "")}
    return value


def _as_options(value: Any) -> Any:
    return [_as_option(o) for o in value] if isinstance(value, list) else value


def _as_editable(value: Any) -> Any:
    return frozenset(value) if isinstance(value, (list, tuple, set)) else value


class Option(BaseModel):
    """One allowed value of an enum field: stored value, UI label, badge style."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str
    label: str = ""
    css: str = ""


class Field(BaseModel):
    """One frontmatter field: how it serializes, validates, and renders."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = ""
    hint: str = ""  # inline comment shown to a human editor
    group: str = ""  # fields that share one stand together on a form, under this heading
    required: bool = False  # binds every writer, the team included
    # Binds the public intake form alone. A field the team may leave empty on an
    # existing zaak can still be a question a stranger must answer.
    public_required: bool = False
    public: bool = False  # shown on the public /inzien-<token> page
    editable: Annotated[frozenset[str], BeforeValidator(_as_editable)] = frozenset({"team"})
    options: Annotated[list[Option], BeforeValidator(_as_options)] = []  # enum types only

    type: ClassVar[str] = "str"  # the YAML type name
    widget: ClassVar[str] = "text"  # picks templates/fields/<widget>.html
    multi: ClassVar[bool] = False  # YAML block list on disk, CSV in memory
    extra_keys: ClassVar[tuple[str, ...]] = ()  # replaces the declared key when set
    # A kind may keep itself off the overview: a secret, or an access rule, is
    # not a fact about the case and does not belong in a list of cases.
    overview: ClassVar[bool] = True
    # A kind may own no frontmatter key at all. A capability is not case
    # information, so it declares itself here and keeps its value elsewhere.
    ondisk: ClassVar[bool] = True

    @model_validator(mode="after")
    def _check_editable(self) -> Field:
        bad = self.editable - ROLES
        if bad:
            raise ValueError(
                f"Ongeldige rol(len) in editable: {', '.join(sorted(bad))}. "
                f"Kies uit: {', '.join(sorted(ROLES))}."
            )
        if "public" in self.editable and not self.public:
            raise ValueError("editable mag 'public' alleen bevatten als public: true is gezet.")
        return self

    def required_for(self, role: str) -> bool:
        """Whether a form shown to `role` may be submitted with this field empty."""
        return self.required or (role == "public" and self.public_required)

    @property
    def values(self) -> list[str]:
        return [o.value for o in self.options]

    def disk_keys(self, key: str) -> tuple[str, ...]:
        if not self.ondisk:
            return ()
        return self.extra_keys or (key,)

    def comment(self, key: str) -> str:
        """The inline `# ...` hint written next to this disk key."""
        return " | ".join(self.values) if self.options else self.hint

    def check(self, key: str, fm: dict[str, str]) -> None:
        value = (fm.get(key) or "").strip()
        if self.required and not value:
            raise ValueError(f"Veld '{key}' is verplicht.")
        if value and self.options and value not in self.values:
            raise ValueError(
                f"Ongeldige waarde voor '{key}': {value}. Kies uit: {', '.join(self.values)}."
            )

    def cell(self, zaak: object, key: str) -> str:
        """The closed overview row's value. Any kind may be a column, so read the key."""
        return str(getattr(zaak, "frontmatter", {}).get(key) or "")

    def sort_key(self, key: str, fm: dict[str, str]) -> tuple[int, Any]:
        """Where this field puts a zaak in an order. A zaak with no value comes last."""
        value = str(fm.get(key) or "").strip().casefold()
        return (0, value) if value else (1, "")

    def initial(self) -> str:
        return ""
