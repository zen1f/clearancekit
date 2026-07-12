"""DisplayBackend Protocol — pluggable virtual display server interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DisplayBackend(Protocol):
    """Pluggable virtual display server backend.

    Screen dimensions (width, height, depth) are provided at construction
    time, not at start(). This keeps start() side-effect-only and lets
    consumers read screen_size() before or after start.
    """

    async def start(self) -> None:
        """Start the virtual display server.

        Uses dimensions provided at construction time.

        Raises:
            RuntimeError: Binary missing or startup fails.
        """
        ...

    async def stop(self) -> None:
        """Terminate the virtual display server process."""
        ...

    def display_id(self) -> str | None:
        """Display string (e.g. ":99") after start, None before."""
        ...

    def screen_size(self) -> tuple[int, int]:
        """(width, height) — always available (set at construction)."""
        ...
