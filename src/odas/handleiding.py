"""The Dutch manual as text: the whole page, or one section of it.

The file is the only copy. A screen that repeats a rule quotes its section here,
so the manual and the screen cannot drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import markdown
import nh3
from markupsafe import Markup

SOURCE = Path(__file__).resolve().parent / "builtin" / "handleiding.md"


def _render(source: str) -> Markup:
    """Render prose without nl2br: source newlines are only line wrapping."""
    return Markup(nh3.clean(markdown.markdown(source, extensions=["tables"])))


def body() -> Markup:
    return _render(SOURCE.read_text(encoding="utf8"))


def section(heading: str) -> Markup:
    """One section, without its heading. Empty when the manual has no such one.

    A `##` and a `###` heading are both quotable, and a section ends at the next
    heading of either level. A screen quotes the smallest part that answers it.
    """
    source = SOURCE.read_text(encoding="utf8")
    for level in ("## ", "### "):
        _, marker, tail = source.partition(f"\n{level}{heading}\n")
        if marker:
            return _render(re.split(r"\n#{2,3} ", tail, maxsplit=1)[0])
    return Markup()
