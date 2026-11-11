"""Progress feedback for long CLI commands, such as `odas index sync`.

A single line updates in place, its label truncated to the terminal width.
A warning prints as its own line without breaking that live line.
"""

from __future__ import annotations

from types import TracebackType

from rich.progress import BarColumn, MofNCompleteColumn, TextColumn
from rich.progress import Progress as RichProgress


class Progress:
    """Show `[i/total] label`. Use as a context manager."""

    def __init__(self, total: int) -> None:
        self._rich = RichProgress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
        )
        self._task = self._rich.add_task("sync", total=total)

    def __enter__(self) -> Progress:
        self._rich.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._rich.stop()

    def update(self, label: str) -> None:
        """Advance the count by one step and show its label."""
        self._rich.update(self._task, advance=1, description=label)

    def warn(self, msg: str) -> None:
        """Print a warning line without corrupting the live progress line."""
        self._rich.console.print(f"[yellow]⚠[/] {msg}")
