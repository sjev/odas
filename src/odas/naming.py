"""Naming helpers shared by the zaak and log writers: ids, slugs, filenames, dates."""

from __future__ import annotations

import os
import random
import re
import string
import unicodedata
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from odas import clock, zaak

# A volume that encrypts its filenames allows no more than 143 characters per name.
# 100 leaves room for the `.samenvatting.md` a document grows beside it, and for the
# `.tmp` an atomic write adds, with headroom to spare.
MAX_NAME = 100


def write_text_atomic(target: Path, text: str) -> None:
    """Write via a sibling .tmp + os.replace, so a reader never sees a half file."""
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf8")
    os.replace(tmp, target)


def next_letter(taken: set[str]) -> str:
    """First unused ordering letter A..Z. Falls back to Z; the caller de-dups the slug."""
    return next((c for c in string.ascii_uppercase if c not in taken), "Z")


def mint(prefix: str, digits: int, exists: Callable[[str], object | None]) -> str:
    """Random {prefix}{digits digits}, collision-checked via `exists`."""
    low, high = 10 ** (digits - 1), 10**digits - 1
    while True:
        ref = f"{prefix}{random.randint(low, high)}"
        if exists(ref) is None:
            return ref


def mint_ref(prefix: str) -> str:
    """Random {prefix}-NNNNN, collision-checked against existing folders."""
    return mint(f"{prefix}-", 5, zaak.find)


def looks_like_ref(text: str) -> bool:
    """Whether a string has the shape `mint` gives, so a typo is told from a port scan."""
    return bool(re.fullmatch(r"[a-z]{2}-\d{5}", text))


def slugify(text: str) -> str:
    """ascii, lowercased, hyphenated, cut to MAX_NAME; '' if nothing usable."""
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")[:MAX_NAME].strip("-")


def _safe_filename(name: str, taken: set[str]) -> str:
    """Path-traversal-safe filename: slugified stem + kept extension, de-duped."""
    stem, dot, ext = name.rpartition(".")
    stem = slugify(stem or name) or "bestand"
    ext = slugify(ext) if dot else ""
    base = f"{stem}.{ext}" if ext else stem
    candidate = base
    i = 2
    while candidate in taken:
        candidate = f"{stem}-{i}.{ext}" if ext else f"{stem}-{i}"
        i += 1
    taken.add(candidate)
    return candidate


def _parse_date(value: str) -> str:
    """Validate a JJJJ-MM-DD date string, defaulting to today. Raises ValueError (Dutch)."""
    value = (value or "").strip()
    if not value:
        return clock.now().strftime("%Y-%m-%d")
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Ongeldige datum: {value}. Gebruik JJJJ-MM-DD.") from None
