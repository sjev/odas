"""Plain text out of an HTML mail part, so the log on disk stays readable."""

from __future__ import annotations

import re
from html.parser import HTMLParser

# A tag that ends a line on screen ends a line here too.
_BLOCK = frozenset({"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"})
_SKIP = frozenset({"script", "style", "head"})


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skipping += 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skipping = max(0, self._skipping - 1)
        elif tag in _BLOCK and tag != "br":  # `<br/>` closes itself; one break, not two
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def to_text(html: str) -> str:
    """The readable text of an HTML fragment. A block tag becomes a line break."""
    parser = _Stripper()
    parser.feed(html)
    parser.close()
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", "".join(parser.parts))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def part_text(content: str, content_type: str) -> str:
    """The text of a mail part: an HTML part is stripped, a plain one is kept as it is."""
    return to_text(content) if content_type == "text/html" else content.strip()
