"""Built-in CF challenge solvers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Protocol, runtime_checkable

from clearancekit._internal.clicker import click_with_trajectory, ensure_supported
from clearancekit.challenges.constants import (
    CF_IFRAME_SRC,
    INTERACTIVE_TEXTS,
    SUCCESS_TEXTS,
)
from clearancekit.challenges.types import ChallengeKind, SolveResult
from clearancekit.transports.base import BrowserDriver

log = logging.getLogger(__name__)


@runtime_checkable
class ChallengeSolver(Protocol):
    """Acts on a challenge to push the page forward."""

    name: str
    handles: set[ChallengeKind]

    async def solve(
        self,
        driver: BrowserDriver,
        kind: ChallengeKind,
        *,
        display: str | None = None,
    ) -> SolveResult:
        """Run the solver against ``driver`` for a challenge of ``kind``."""
        ...


async def _get_iframe_text(
    driver: BrowserDriver,
) -> str | None:
    """Read CF iframe text via find_iframe."""
    iframe = await driver.find_iframe(CF_IFRAME_SRC)
    return iframe.text if iframe else None


async def _wait_for_interactive(
    driver: BrowserDriver, timeout: float, poll: float = 0.5
) -> bool:
    """Poll iframe text until 'Verify you are human' appears or timeout."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        text = await _get_iframe_text(driver)
        if text and any(k in text for k in INTERACTIVE_TEXTS):
            return True
        if text and any(k in text for k in SUCCESS_TEXTS):
            return False
        await asyncio.sleep(poll)
    return False


async def _poll_success(
    driver: BrowserDriver,
    timeout: float,
    poll: float = 0.5,
    *,
    initial_cf: str | None = None,
) -> bool:
    """Poll iframe text for 'Success' and cf_clearance cookie."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        text = await _get_iframe_text(driver)
        if text and any(k in text for k in SUCCESS_TEXTS):
            return True
        cookies = await driver.get_cookies()
        cf = next(
            (c for c in cookies if c.name == "cf_clearance"),
            None,
        )
        if cf is not None and (
            initial_cf is None or cf.value != initial_cf
        ):
            return True
        await asyncio.sleep(poll)
    return False


class PassiveWaitSolver:
    """For ``CF_PASSIVE``: check actual state instead of blind sleep."""

    name = "passive_wait"
    handles = {ChallengeKind.CF_PASSIVE}

    async def solve(
        self,
        driver: BrowserDriver,
        kind: ChallengeKind,
        *,
        display: str | None = None,
    ) -> SolveResult:
        """Check if challenge resolved; if not, throttle."""
        t0 = time.monotonic()
        text = await _get_iframe_text(driver)
        if text and any(k in text for k in SUCCESS_TEXTS):
            log.debug("[%s] iframe text shows success", self.name)
            return SolveResult(
                success=True,
                solver_name=self.name,
                elapsed_s=time.monotonic() - t0,
            )
        cookies = await driver.get_cookies()
        if any(c.name == "cf_clearance" for c in cookies):
            log.debug("[%s] cf_clearance cookie found", self.name)
            return SolveResult(
                success=True,
                solver_name=self.name,
                elapsed_s=time.monotonic() - t0,
            )
        await asyncio.sleep(0.5)
        log.debug(
            "[%s] not yet resolved, returning failure",
            self.name,
        )
        return SolveResult(
            success=False,
            solver_name=self.name,
            elapsed_s=time.monotonic() - t0,
        )


class OSClickSolver:
    """For CF_INTERACTIVE: locate CF iframe, OS-click via xdotool.

    Immune to CDP event detection.
    Requires Linux + X11 + xdotool.
    """

    name = "os_click"
    handles = {ChallengeKind.CF_INTERACTIVE}

    CHECKBOX_X_OFFSET = 28

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        post_click_timeout: float = 15.0,
        post_click_poll: float = 1,
        pre_click_delay: float = 10.0,
    ) -> None:
        self._max = max_attempts
        self._post_click_timeout = post_click_timeout
        self._post_click_poll = post_click_poll
        self._pre_click_delay = pre_click_delay

    async def _get_checkbox_screen_coords(
        self, driver: BrowserDriver
    ) -> tuple[int, int] | None:
        """Iframe rect -> screen coords for checkbox."""
        info = await driver.find_iframe(CF_IFRAME_SRC)
        if info is None:
            log.debug(
                "[%s] CF iframe not found (src=%s)",
                self.name,
                CF_IFRAME_SRC,
            )
            return None
        rect = info.rect
        log.debug(
            "[%s] iframe rect: x=%.1f y=%.1f w=%.1f h=%.1f",
            self.name,
            rect.x,
            rect.y,
            rect.width,
            rect.height,
        )
        vx = rect.x + self.CHECKBOX_X_OFFSET
        vy = rect.y + rect.height / 2
        win_x = float(
            await driver.evaluate("window.screenX") or 0,
        )
        win_y = float(
            await driver.evaluate("window.screenY") or 0,
        )
        chrome_h = float(
            await driver.evaluate(
                "window.outerHeight - window.innerHeight"
            )
            or 0
        )
        sx, sy = int(win_x + vx), int(win_y + chrome_h + vy)
        log.debug(
            "[%s] screen coords: (%d, %d)"
            "  [win=(%d,%d) chrome_h=%d]",
            self.name,
            sx,
            sy,
            int(win_x),
            int(win_y),
            int(chrome_h),
        )
        return (sx, sy)

    async def solve(
        self,
        driver: BrowserDriver,
        kind: ChallengeKind,
        *,
        display: str | None = None,
    ) -> SolveResult:
        """Wait for checkbox, then OS-click via xdotool."""
        log.debug(
            "[%s] starting — max_attempts=%d, display=%s",
            self.name,
            self._max,
            display,
        )
        ensure_supported()
        t0 = time.monotonic()

        await _wait_for_interactive(driver, self._pre_click_delay)

        initial_cookies = await driver.get_cookies()
        initial_cf = next(
            (
                c.value
                for c in initial_cookies
                if c.name == "cf_clearance"
            ),
            None,
        )
        log.debug(
            "[%s] baseline cf_clearance=%s",
            self.name,
            initial_cf[:8] + "..." if initial_cf else None,
        )

        for attempt in range(1, self._max + 1):
            log.debug(
                "[%s] attempt %d/%d",
                self.name,
                attempt,
                self._max,
            )
            coords = await self._get_checkbox_screen_coords(driver)
            if coords is None:
                log.debug(
                    "[%s] no coords, retrying in 1s", self.name,
                )
                await asyncio.sleep(1.0)
                continue
            log.debug(
                "[%s] clicking at (%d, %d)",
                self.name,
                coords[0],
                coords[1],
            )
            click_with_trajectory(
                x=coords[0], y=coords[1], display=display,
            )
            if await _poll_success(
                driver,
                self._post_click_timeout,
                self._post_click_poll,
                initial_cf=initial_cf,
            ):
                elapsed = time.monotonic() - t0
                log.debug(
                    "[%s] success on attempt %d, elapsed=%.2fs",
                    self.name,
                    attempt,
                    elapsed,
                )
                return SolveResult(
                    success=True,
                    solver_name=self.name,
                    elapsed_s=elapsed,
                )
        elapsed = time.monotonic() - t0
        log.debug(
            "[%s] all %d attempts exhausted, elapsed=%.2fs",
            self.name,
            self._max,
            elapsed,
        )
        return SolveResult(
            success=False,
            solver_name=self.name,
            elapsed_s=elapsed,
        )
