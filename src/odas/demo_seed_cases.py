"""The demo's bezwaar and dossier, written through the app's own writers.

Frontmatter is never hand-written: every field here goes through `zaak_create`,
`index_write` and `log_write`, so what a visitor reads is a shape the current
schema in `config.yaml` accepts. See `demo_seed.build_zaken`. The third case,
the Woo-verzoek, lives in `demo_seed_woo.py` and reuses `set_body` from here.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path


def set_body(folder: Path, body: str) -> None:
    """Replace the body, keeping the frontmatter the writers already canonicalised."""
    from odas import zaak, zaak_create
    from odas.appconfig import type_fields

    z = zaak.load(folder)
    zaak_create.write_index(folder, z.frontmatter, body, type_fields(z.soort))


def bezwaar_kapvergunning(today: date, termijn_days: int) -> str:
    """The bezwaar: a permit granted with no boomeffectanalyse attached."""
    from odas import index_write, log_write, zaak_create
    from odas.config import Config

    bezwaar = zaak_create.create_minimal("Bezwaar kapvergunning Molenstraat", "procedure")
    folder = Config().zaken_dir / f"{bezwaar.ref}-bezwaar-kapvergunning-molenstraat"
    index_write.update_fields(
        folder,
        {
            "status": "in_behandeling",
            "fase": "bezwaar",
            "wederpartij": "Gemeente Middelvoort",
            "locatie": "52.0885,5.1123",
            "termijn_datum": (today + timedelta(days=termijn_days)).isoformat(),
            "termijn_soort": "bezwaar",
        },
        by="demo",
    )
    log_write.write_log_entry(
        folder,
        "IN",
        "Kapvergunning verleend",
        "De gemeente verleent een vergunning voor het kappen van elf lindes\n"
        "aan de Molenstraat. De boomeffectanalyse ontbreekt bij het besluit.\n",
        datum=(today - timedelta(days=30)).isoformat(),
    )
    log_write.write_log_entry(
        folder,
        "UIT",
        "Bezwaarschrift ingediend",
        "Bezwaar tegen de kapvergunning: de boomeffectanalyse ontbreekt en de\n"
        "herplantplicht is niet als voorschrift opgenomen.\n",
        aan="bezwaar@middelvoort.example.nl",
        datum=(today - timedelta(days=16)).isoformat(),
    )
    set_body(
        folder,
        """## Samenvatting

De gemeente verleende een kapvergunning voor elf lindes aan de Molenstraat. De
boomeffectanalyse ontbrak bij het besluit en er is geen herplantplicht
opgenomen.

**Stand van zaken**: het bezwaarschrift is ingediend. De hoorzitting is nog niet
gepland.

**Actie demo**: de boomeffectanalyse opvragen bij de gemeente.
""",
    )
    return bezwaar.ref


def dossier_groenbeheer(woo_ref: str, bezwaar_ref: str) -> None:
    """The dossier grouping both cases: same municipality, same street."""
    from odas import index_write, zaak_create
    from odas.config import Config

    groen = zaak_create.create_minimal("Dossier groenbeheer Middelvoort", "dossier")
    folder = Config().zaken_dir / f"{groen.ref}-dossier-groenbeheer-middelvoort"
    index_write.update_fields(folder, {"zaken": f"{woo_ref}, {bezwaar_ref}"}, by="demo")
    set_body(
        folder,
        """## Samenvatting

Alles wat in Middelvoort over openbaar groen loopt, bij elkaar. Twee zaken
hangen hieronder: het Woo-verzoek over het verkeersbesluit en het bezwaar tegen
de kapvergunning. Beide gaan over dezelfde straat.
""",
    )


def overleg_werkverdeling() -> None:
    """The internal discussion: a type with no indiener and no deadline."""
    from odas import index_write, zaak_create
    from odas.config import Config

    overleg = zaak_create.create_minimal("Werkverdeling Middelvoort", "overleg")
    folder = Config().zaken_dir / f"{overleg.ref}-werkverdeling-middelvoort"
    index_write.update_fields(
        folder,
        {"status": "in_behandeling", "eigenaar": "ilse@demo.dasopen.nl"},
        by="demo",
    )
    set_body(
        folder,
        """## Waar dit over gaat

Wie doet wat in Middelvoort. Het bezwaar en het Woo-verzoek lopen naast elkaar
en raken dezelfde ambtenaar, dus we willen niet dubbel bellen.

Afgesproken: Ilse voert het woord bij de gemeente. John schrijft de stukken.
De hoorzitting bereiden we samen voor.
""",
    )
