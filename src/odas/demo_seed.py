"""Generate the demo's example zaken and fetch its law text, live.

Runs at `odas demo init`/`reset` time (`cli_demo.py`), never as a separate
build-then-commit step: the case scenario goes through the app's own writers
every time, so it is always frontmatter the current schema accepts.
"""

from __future__ import annotations

import random
from datetime import date
from pathlib import Path

from odas import demo_seed_cases
from odas.demo_seed_woo import woo_verzoek

TERMIJN_DAYS = 21  # `cli_demo.reset` reads this back as the offset from today

# The two laws every demo procedure runs on: the Woo the seeded zaak is about,
# and the Awb that gives it its terms.
WETTEN = (("woo", "BWBR0045754"), ("awb", "BWBR0005537"))


def build_zaken() -> None:
    """Write the Woo-verzoek, the bezwaar, their dossier and one overleg into `zaken/`."""
    from odas.config import Config

    random.seed(20260822)  # fixed refs and tokens, so a diff is a diff a person can read
    Config().ensure_dirs()
    today = date.today()

    woo_ref = woo_verzoek(today, TERMIJN_DAYS)
    bezwaar_ref = demo_seed_cases.bezwaar_kapvergunning(today, TERMIJN_DAYS)
    demo_seed_cases.dossier_groenbeheer(woo_ref, bezwaar_ref)
    demo_seed_cases.overleg_werkverdeling()


def fetch_wetten(wetten_dir: Path) -> None:
    """Track the demo's laws, so the law pages and the seeded zaak have their law.

    A law already on disk is left alone, so a reset adds only what is missing.
    Best-effort per law: on failure that law stays absent rather than raising
    through the reset.
    """
    from odas.wetten import add

    for slug, bwb_id in WETTEN:
        if (wetten_dir / slug / "_wet.md").is_file():
            continue
        try:
            law = add(wetten_dir, bwb_id, slug)
        except Exception as exc:  # a reset says why and carries on rather than raising
            print(f"wetten/{slug}: not fetched, the register is unreachable ({exc})")
            continue
        print(f"wetten/{slug}: {law.title} ({law.valid_from})")
