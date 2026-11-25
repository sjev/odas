"""A zaak as one Markdown text: index.md, then each log entry as it is on disk.

The text goes to a chat box, so it carries words only. An attachment is named,
never read in.
"""

from __future__ import annotations

from pathlib import Path

from odas import zaak


def _entry(folder: Path, entry: zaak.LogEntry) -> str:
    path = folder / "log" / entry.name
    source = path / "index.md" if path.is_dir() else path.with_name(f"{entry.name}.md")
    raw = source.read_text(encoding="utf8").strip() if source.is_file() else ""
    part = f"## log/{entry.name}\n\n{raw}\n"
    if entry.attachments:
        names = "\n".join(f"- {Path(a).name}" for a in entry.attachments)
        part += f"\nBijlagen:\n{names}\n"
    return part


def render(folder: Path) -> str:
    """The case text: what the zip holds, minus everything that is not words."""
    index = (folder / "index.md").read_text(encoding="utf8").strip()
    parts = [f"# {folder.name}\n\n{index}\n"]
    parts += [_entry(folder, e) for e in zaak.scan_log(folder)]
    return "\n".join(parts)
