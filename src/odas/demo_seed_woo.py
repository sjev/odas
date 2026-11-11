"""The Woo-verzoek: the demo's one case with an attachment and a summary."""

from __future__ import annotations

from datetime import date, timedelta

from odas.demo_seed_cases import set_body
from odas.demo_seed_pdf import BESLUIT, SAMENVATTING


def woo_verzoek(today: date, termijn_days: int) -> str:
    """The Woo-verzoek: a partial disclosure, one attachment, its own summary."""
    from odas import index, index_write, log_write, zaak_create
    from odas.config import Config

    woo = zaak_create.create_minimal("Woo-verzoek verkeersbesluit Molenstraat", "procedure")
    folder = Config().zaken_dir / f"{woo.ref}-woo-verzoek-verkeersbesluit-molenstraat"
    index_write.update_fields(
        folder,
        {
            "status": "in_behandeling",
            "fase": "verzoek",
            "wederpartij": "Gemeente Middelvoort",
            "locatie": "52.0891,5.1101",
            "termijn_datum": (today + timedelta(days=termijn_days)).isoformat(),
            "termijn_soort": "bezwaar",
        },
        by="demo",
    )
    log_write.write_log_entry(
        folder,
        "UIT",
        "Woo-verzoek ingediend",
        "Verzoek om alle stukken achter het verkeersbesluit Molenstraat: het\n"
        "verkeerskundig onderzoek, de interne advisering en de correspondentie\n"
        "met de provincie.\n",
        aan="info@middelvoort.example.nl",
        datum=(today - timedelta(days=95)).isoformat(),
    )
    log_write.write_log_entry(
        folder,
        "IN",
        "Ontvangstbevestiging",
        "De gemeente bevestigt de ontvangst en verdaagt de beslistermijn met\nvier weken.\n",
        datum=(today - timedelta(days=88)).isoformat(),
    )
    entry = log_write.write_log_entry(
        folder,
        "IN",
        "Besluit gedeeltelijke openbaarmaking",
        "Het college wijst het verzoek gedeeltelijk toe. De interne notitie\n"
        "blijft geheim op grond van artikel 5.2 Woo.\n",
        attachments=[("besluit-woo-0143.pdf", BESLUIT)],
        datum=(today - timedelta(days=41)).isoformat(),
    )
    # Written through the app's own summary writer, so the hash beside the file
    # is the one the page checks before it shows the text.
    pdf = entry / "besluit-woo-0143.pdf"
    index.write_summary(pdf, index.digest(pdf), SAMENVATTING, by="demo")
    set_body(
        folder,
        """## Samenvatting

De gemeente Middelvoort nam een verkeersbesluit voor de Molenstraat zonder het
onderliggende onderzoek te publiceren. Met een Woo-verzoek zijn de stukken
opgevraagd.

**Stand van zaken**: het college heeft het verzoek gedeeltelijk toegewezen. Het
verkeerskundig onderzoek is verstrekt. De interne notitie van 3 april is
geweigerd op grond van artikel 5.2 lid 1 Woo.

**Actie demo**: bezwaar opstellen tegen de weigering. Het college motiveert niet
waarom een geanonimiseerde versie niet kan.
""",
    )
    log_write.write_log_entry(
        folder,
        "LOG",
        "Weigering onvoldoende gemotiveerd",
        "Het college motiveert niet waarom een geanonimiseerde versie van de\n"
        "notitie niet kan. Dat is de kern van het bezwaar.\n",
        datum=(today - timedelta(days=38)).isoformat(),
    )
    return woo.ref
