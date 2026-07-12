"""XvfbBackend: startup detection via -displayfd or socket polling."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

_X11_SOCKET_DIR = Path("/tmp/.X11-unix")


class XvfbBackend:
    """DisplayBackend implementation using Xvfb.

    Screen dimensions are fixed at construction. ``start()`` launches the
    process; ``stop()`` tears it down.
    """

    def __init__(
        self,
        *,
        width: int = 1920,
        height: int = 1080,
        depth: int = 24,
        display_num: int | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._width = width
        self._height = height
        self._depth = depth
        self._display_num = display_num
        self._timeout = timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._display_id: str | None = None

    def display_id(self) -> str | None:
        """Display string (e.g. ":99") after start, None before."""
        return self._display_id

    def screen_size(self) -> tuple[int, int]:
        """(width, height) — always available."""
        return (self._width, self._height)

    async def start(self) -> None:
        """Start Xvfb with dimensions configured at construction.

        Raises:
            RuntimeError: Xvfb binary missing or startup timeout.
        """
        if self._display_num is not None:
            await self._start_fixed()
        else:
            await self._start_auto()

    async def _start_fixed(self) -> None:
        """Start Xvfb on a user-specified display number, poll socket for readiness."""
        display_arg = f":{self._display_num}"
        screen_spec = f"{self._width}x{self._height}x{self._depth}"
        try:
            self._proc = await asyncio.create_subprocess_exec(
                "Xvfb",
                display_arg,
                "-screen",
                "0",
                screen_spec,
                "-nolisten",
                "tcp",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Xvfb binary not found; install with `apt install xvfb`"
            ) from None

        socket_path = _X11_SOCKET_DIR / f"X{self._display_num}"
        poll_interval = 0.05
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            if socket_path.exists():
                self._display_id = display_arg
                return
            if self._proc.returncode is not None:
                self._proc = None
                raise RuntimeError(
                    f"Xvfb exited immediately (display {display_arg} may be in use)"
                )
            await asyncio.sleep(poll_interval)

        self._proc.terminate()
        await self._proc.wait()
        self._proc = None
        raise RuntimeError(f"Xvfb did not become ready within {self._timeout}s")

    async def _start_auto(self) -> None:
        """Start Xvfb with -displayfd for automatic display allocation."""
        screen_spec = f"{self._width}x{self._height}x{self._depth}"
        read_fd, write_fd = os.pipe()
        try:
            self._proc = await asyncio.create_subprocess_exec(
                "Xvfb",
                "-displayfd",
                str(write_fd),
                "-screen",
                "0",
                screen_spec,
                "-nolisten",
                "tcp",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                pass_fds=(write_fd,),
            )
        except FileNotFoundError:
            os.close(read_fd)
            os.close(write_fd)
            raise RuntimeError(
                "Xvfb binary not found; install with `apt install xvfb`"
            ) from None

        os.close(write_fd)

        loop = asyncio.get_running_loop()
        with os.fdopen(read_fd, "r") as f:
            try:
                line = await asyncio.wait_for(
                    loop.run_in_executor(None, f.readline),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                self._proc.terminate()
                await self._proc.wait()
                self._proc = None
                raise RuntimeError(
                    f"Xvfb did not become ready within {self._timeout}s"
                ) from None

        self._display_id = f":{int(line.strip())}"

    async def stop(self) -> None:
        """Terminate the Xvfb process."""
        if self._proc is None:
            return
        self._proc.terminate()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            self._proc.kill()
            await self._proc.wait()
        self._proc = None
        self._display_id = None


@asynccontextmanager
async def xvfb(
    *,
    width: int = 1920,
    height: int = 1080,
    depth: int = 24,
    timeout: float = 5.0,
    display_num: int | None = None,
) -> AsyncIterator[str]:
    """Async context manager: start Xvfb, yield display_id, cleanup on exit.

    Args:
        width: Screen width in pixels.
        height: Screen height in pixels.
        depth: Color depth.
        timeout: Max seconds to wait for Xvfb to become ready.
        display_num: Fixed display number. None = auto-allocate.

    Yields:
        Display string (e.g. ":99").

    Raises:
        RuntimeError: If Xvfb fails to start.
    """
    b = XvfbBackend(
        width=width,
        height=height,
        depth=depth,
        display_num=display_num,
        timeout=timeout,
    )
    await b.start()
    try:
        yield b.display_id()  # type: ignore[misc]
    finally:
        await b.stop()
