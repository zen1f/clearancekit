"""Tests for clearancekit._internal.clicker."""

import os
from unittest.mock import MagicMock, patch

import pytest

from clearancekit._internal.clicker import (
    click,
    click_with_trajectory,
    ensure_supported,
)
from clearancekit.errors import CFAutoClickUnsupported


class TestEnsureSupported:
    def test_raises_on_non_linux(self):
        with (
            patch("sys.platform", "darwin"),
            pytest.raises(CFAutoClickUnsupported, match="Linux"),
        ):
            ensure_supported()

    def test_raises_on_missing_xdotool(self):
        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", return_value=None),
            pytest.raises(CFAutoClickUnsupported, match="xdotool"),
        ):
            ensure_supported()

    def test_passes_when_linux_and_xdotool_present(self):
        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", return_value="/usr/bin/xdotool"),
        ):
            ensure_supported()

    def test_raises_on_wayland_without_x11(self):
        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", return_value="/usr/bin/xdotool"),
            patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=True),
            pytest.raises(CFAutoClickUnsupported, match="Wayland"),
        ):
            ensure_supported()

    def test_passes_on_wayland_with_xwayland_display(self):
        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", return_value="/usr/bin/xdotool"),
            patch.dict(
                os.environ,
                {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"},
                clear=True,
            ),
        ):
            ensure_supported()


class TestClick:
    def test_invokes_xdotool_with_coords_and_display(self):
        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", return_value="/usr/bin/xdotool"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            click(x=100, y=200, display=":99")
            mock_run.assert_called_once()
            args = mock_run.call_args.args[0]
            assert "xdotool" in args[0]
            assert "100" in args and "200" in args
            assert mock_run.call_args.kwargs["env"]["DISPLAY"] == ":99"

    def test_raises_on_non_linux(self):
        with (
            patch("sys.platform", "darwin"),
            pytest.raises(CFAutoClickUnsupported),
        ):
            click(x=0, y=0)


class TestClickWithTrajectory:
    def test_calls_xdotool_with_movement_and_click(self):
        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", return_value="/usr/bin/xdotool"),
            patch("subprocess.run") as mock_run,
            patch("time.sleep"),
            patch("random.randint", return_value=400),
            patch("random.random", return_value=0.0),
        ):
            mock_run.return_value = MagicMock(returncode=0)
            click_with_trajectory(x=500, y=300, display=":1")

            calls = mock_run.call_args_list
            # Initial move + 10 trajectory steps + mousedown + mouseup = 13 calls
            assert len(calls) == 13

            # First call: initial position
            assert calls[0].args[0][:2] == ["xdotool", "mousemove"]

            # Last two calls: mousedown and mouseup
            assert calls[-2].args[0] == ["xdotool", "mousedown", "1"]
            assert calls[-1].args[0] == ["xdotool", "mouseup", "1"]

            # All calls have the correct DISPLAY env
            for c in calls:
                assert c.kwargs["env"]["DISPLAY"] == ":1"

    def test_raises_on_non_linux(self):
        with (
            patch("sys.platform", "darwin"),
            pytest.raises(CFAutoClickUnsupported),
        ):
            click_with_trajectory(x=0, y=0)
