"""Tests for built-in challenge solvers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clearancekit.challenges.solvers import (
    ChallengeSolver,
    OSClickSolver,
    PassiveWaitSolver,
)
from clearancekit.challenges.types import ChallengeKind
from clearancekit.transports.base import IframeInfo, ViewportRect

_SLEEP = "clearancekit.challenges.solvers.asyncio.sleep"
_ENSURE = "clearancekit.challenges.solvers.ensure_supported"
_CLICK_TRAJ = "clearancekit.challenges.solvers.click_with_trajectory"

_CF_SRC = "https://challenges.cloudflare.com/turnstile/xxx"


def _make_iframe(text=None):
    return IframeInfo(
        src=_CF_SRC,
        rect=ViewportRect(x=100.0, y=200.0, width=300.0, height=65.0),
        text=text,
    )


def _make_driver(
    *,
    iframe=None,
    cookies=None,
    evaluate_return=0.0,
):
    driver = MagicMock()
    driver.find_iframe = AsyncMock(return_value=iframe)
    driver.get_cookies = AsyncMock(return_value=cookies or [])
    driver.evaluate = AsyncMock(return_value=evaluate_return)
    return driver


class TestPassiveWaitSolver:
    def test_handles_set(self):
        s = PassiveWaitSolver()
        assert s.handles == {ChallengeKind.CF_PASSIVE}

    @pytest.mark.asyncio
    async def test_returns_success_when_iframe_shows_success(self):
        s = PassiveWaitSolver()
        driver = _make_driver(iframe=_make_iframe(text="Success"))
        with patch(_SLEEP, new_callable=AsyncMock):
            r = await s.solve(driver, ChallengeKind.CF_PASSIVE)
        assert r.success is True
        assert r.solver_name == "passive_wait"

    @pytest.mark.asyncio
    async def test_returns_success_when_clearance_cookie_exists(self):
        s = PassiveWaitSolver()
        driver = _make_driver(
            cookies=[
                SimpleNamespace(name="cf_clearance", value="tok"),
            ],
        )
        with patch(_SLEEP, new_callable=AsyncMock):
            r = await s.solve(driver, ChallengeKind.CF_PASSIVE)
        assert r.success is True

    @pytest.mark.asyncio
    async def test_returns_failure_when_not_resolved(self):
        s = PassiveWaitSolver()
        driver = _make_driver()
        with patch(_SLEEP, new_callable=AsyncMock):
            r = await s.solve(driver, ChallengeKind.CF_PASSIVE)
        assert r.success is False


class TestOSClickSolver:
    @pytest.mark.asyncio
    async def test_solve_finds_iframe_clicks_and_succeeds(self):
        driver = _make_driver(
            iframe=_make_iframe(text="Verify you are human"),
        )
        driver.evaluate = AsyncMock(side_effect=[
            # _wait_for_interactive polls find_iframe, not evaluate
            # _get_checkbox_screen_coords calls evaluate 3x:
            10.0,   # window.screenX
            50.0,   # window.screenY
            80.0,   # outerHeight - innerHeight
        ])
        driver.get_cookies = AsyncMock(side_effect=[
            [],
            [SimpleNamespace(name="cf_clearance", value="tok")],
        ])

        s = OSClickSolver(
            max_attempts=1,
            post_click_timeout=1.0,
            post_click_poll=0.01,
            pre_click_delay=0.01,
        )
        with (
            patch(_ENSURE),
            patch(_CLICK_TRAJ) as mock_click,
            patch(_SLEEP, new_callable=AsyncMock),
        ):
            r = await s.solve(
                driver, ChallengeKind.CF_INTERACTIVE,
                display=":99",
            )

        assert r.success is True
        assert r.solver_name == "os_click"
        expected_y = int(50 + 80 + 200 + 65 / 2)
        mock_click.assert_called_once_with(
            x=138, y=expected_y, display=":99"
        )

    @pytest.mark.asyncio
    async def test_solve_returns_failure_when_no_iframe(self):
        driver = _make_driver(
            iframe=_make_iframe(text="Verify you are human"),
        )
        # _wait_for_interactive gets iframe with text
        # _get_checkbox_screen_coords gets None (no iframe for rect)
        driver.find_iframe = AsyncMock(side_effect=[
            _make_iframe(text="Verify you are human"),  # wait
            None,  # attempt 1 coords
            None,  # attempt 2 coords
        ])

        s = OSClickSolver(
            max_attempts=2, pre_click_delay=0.01,
        )
        with (
            patch(_ENSURE),
            patch(_SLEEP, new_callable=AsyncMock),
        ):
            r = await s.solve(
                driver, ChallengeKind.CF_INTERACTIVE
            )

        assert r.success is False
        assert r.solver_name == "os_click"

    @pytest.mark.asyncio
    async def test_solve_returns_failure_no_clearance_cookie(self):
        driver = _make_driver(
            iframe=_make_iframe(text="Verify you are human"),
            cookies=[
                SimpleNamespace(name="other_cookie", value="val"),
            ],
        )
        driver.evaluate = AsyncMock(return_value=0.0)

        s = OSClickSolver(
            max_attempts=1,
            post_click_timeout=0.05,
            post_click_poll=0.01,
            pre_click_delay=0.01,
        )
        with (
            patch(_ENSURE),
            patch(_CLICK_TRAJ),
            patch(_SLEEP, new_callable=AsyncMock),
        ):
            r = await s.solve(
                driver, ChallengeKind.CF_INTERACTIVE
            )

        assert r.success is False


def test_solvers_are_runtime_checkable():
    assert isinstance(PassiveWaitSolver(), ChallengeSolver)
