"""Zaak creation: new folders (full intake or minimal) and index.md writes."""

from __future__ import annotations

import logging
from pathlib import Path

from odas import audit, clock, folder_store, schema, zaak
from odas.appconfig import all_types, intake_type, type_fields, type_prefix
from odas.config import Config
from odas.fields import ReplyTokenField
from odas.naming import mint_ref, slugify, write_text_atomic

log = logging.getLogger(__name__)


def write_index(
    folder: Path, fm: dict[str, str], body: str, fields: dict[str, schema.Field]
) -> None:
    """Atomically write canonical frontmatter (all schema fields) + body."""
    write_text_atomic(folder / "index.md", schema.dump(fm, body, fields))


def initial_fm(fields: dict[str, schema.Field], **values: str) -> dict[str, str]:
    """Frontmatter for a new record: each field's `initial()`, then the given values."""
    fm = {k: f.initial() for key, f in fields.items() for k in f.disk_keys(key)}
    fm.update(values)
    return fm


def mint_token(folder: Path, fields: dict[str, schema.Field]) -> None:
    """Give a shareable type its capability, beside the record and not inside it."""
    if any(isinstance(f, ReplyTokenField) for f in fields.values()):
        folder_store.write_token(folder, ReplyTokenField.mint())


def create_zaak(
    values: dict[str, str],
    titel: str,
    body: str = "",
    documents: list[tuple[str, bytes]] | None = None,
    by: str = "indiener",
) -> zaak.Zaak:
    """Create a zaak of the public-intake type. `values` are its declared disk keys."""
    from odas import log_write

    soort = intake_type()
    ref = mint_ref(type_prefix(soort))
    folder = Config().zaken_dir / f"{ref}-{slugify(titel) or 'zaak'}"
    folder.mkdir(parents=True)

    fields = type_fields(soort)
    fm = initial_fm(
        fields,
        **values,
        id=ref,
        soort=soort,
        titel=titel,
        status="nieuw",
        aangemaakt=clock.stamp(),
    )

    write_index(folder, fm, body, fields)
    mint_token(folder, fields)

    audit.write(folder, "zaak aangemaakt", by)
    log.info(f"Zaak created: ref={folder.name!r} soort={soort!r}")

    # Always one entry, with or without attachments: the submission is an incoming
    # message, so it sets the flag until a person clears it.
    log_write.write_log_entry(
        folder,
        "IN",
        "indiening",
        "Indiening via het webformulier.",
        attachments=documents,
        by=by,
    )

    return zaak.load(folder)


def create_minimal(titel: str, soort: str, by: str = "intaketeam") -> zaak.Zaak:
    """Create a near-empty zaak of the given soort. Raises `ValueError` if titel is empty.

    The folder slug is frozen here: `titel` is editable afterwards and is the
    rename mechanism, but the folder never moves.
    """
    titel = titel.strip()
    if not titel:
        raise ValueError("Geef een titel op.")
    if soort not in all_types():
        raise ValueError(f"Onbekend type: {soort}.")

    ref = mint_ref(type_prefix(soort))
    folder = Config().zaken_dir / f"{ref}-{slugify(titel) or 'zaak'}"
    folder.mkdir(parents=True)

    fields = type_fields(soort)
    fm = initial_fm(
        fields,
        id=ref,
        soort=soort,
        titel=titel,
        status="nieuw" if "status" in fields else "",
        aangemaakt=clock.stamp(),
    )
    write_index(folder, fm, "", fields)
    mint_token(folder, fields)
    audit.write(folder, "zaak aangemaakt", by)
    return zaak.load(folder)
