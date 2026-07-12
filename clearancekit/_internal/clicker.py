"""OS-level mouse click via ``xdotool`` (Linux X11 only).

Non-Linux platforms raise ``CFAutoClickUnsupported``. Mac/Windows users
should run clearancekit inside a Linux container.
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import time

from clearancekit.errors import CFAutoClickUnsupported


def ensure_supported() -> None:
    """Raise ``CFAutoClickUnsupported`` if the platform cannot auto-click.

    Conditions checked:
      - ``sys.platform`` must start with ``linux``
      - ``xdotool`` binary must be on PATH
      - Not a Wayland session without an X11 compatibility layer
    """
    if not sys.platform.startswith("linux"):
        raise CFAutoClickUnsupported(
            f"clearancekit auto-click requires Linux + X11; got {sys.platform}",
            platform=sys.platform,
        )
    if shutil.which("xdotool") is None:
        raise CFAutoClickUnsupported(
            "xdotool not found on PATH; install with `apt install xdotool`",
        )
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" and not os.environ.get(
        "DISPLAY"
    ):
        raise CFAutoClickUnsupported(
            "Wayland session without X11 compatibility layer; "
            "set DISPLAY or pass a DisplayBackend to Session.create()",
        )


def click(x: int, y: int, *, display: str | None = None) -> None:
    """Move mouse to (x, y) and click left button via xdotool.

    Args:
        x: Absolute screen X coordinate.
        y: Absolute screen Y coordinate.
        display: X display id; ``None`` = inherit ``$DISPLAY``.

    Raises:
        CFAutoClickUnsupported: Platform unsupported (see ``ensure_supported``).
        subprocess.CalledProcessError: If xdotool exits non-zero.
    """
    ensure_supported()
    env = os.environ.copy()
    if display:
        env["DISPLAY"] = display
    subprocess.run(
        ["xdotool", "mousemove", str(x), str(y), "click", "1"],
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def click_with_trajectory(x: int, y: int, *, display: str | None = None) -> None:
    """Move mouse with human-like trajectory, then click.

    Simulates natural mouse movement using smoothstep interpolation with
    random jitter, followed by a mousedown/mouseup pair with realistic
    timing delays.

    Args:
        x: Absolute screen X coordinate of click target.
        y: Absolute screen Y coordinate of click target.
        display: X display id; ``None`` = inherit ``$DISPLAY``.

    Raises:
        CFAutoClickUnsupported: Platform unsupported (see ``ensure_supported``).
        subprocess.CalledProcessError: If xdotool exits non-zero.
    """
    ensure_supported()
    env = os.environ.copy()
    if display:
        env["DISPLAY"] = display

    sx, sy = random.randint(200, 600), random.randint(100, 300)
    subprocess.run(
        ["xdotool", "mousemove", str(sx), str(sy)],
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.2)

    steps = 10
    for s in range(1, steps + 1):
        t = s / steps
        ease = t * t * (3 - 2 * t)  # smoothstep
        mx = int(sx + (x - sx) * ease + random.randint(-3, 3))
        my = int(sy + (y - sy) * ease + random.randint(-2, 2))
        subprocess.run(
            ["xdotool", "mousemove", str(mx), str(my)],
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.02 + random.random() * 0.04)

    time.sleep(0.1 + random.random() * 0.1)
    subprocess.run(
        ["xdotool", "mousedown", "1"],
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.05 + random.random() * 0.07)
    subprocess.run(
        ["xdotool", "mouseup", "1"],
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
