"""Tests for clearancekit.display: XvfbBackend + xvfb context manager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clearancekit.display import DisplayBackend, XvfbBackend, xvfb


class TestDisplayBackendProtocol:
    def test_xvfb_backend_is_display_backend(self):
        assert isinstance(XvfbBackend(), DisplayBackend)


class TestXvfbBackend:
    def test_display_id_is_none_before_start(self):
        backend = XvfbBackend()
        assert backend.display_id() is None

    @pytest.mark.asyncio
    async def test_start_sets_display_id(self):
        proc = MagicMock()
        proc.terminate = MagicMock()
        proc.wait = AsyncMock(return_value=0)

        fake_file = MagicMock()
        fake_file.__enter__ = MagicMock(return_value=fake_file)
        fake_file.__exit__ = MagicMock(return_value=False)

        async def fake_wait_for(coro, *, timeout):
            return "42\n"

        with (
            patch("os.pipe", return_value=(10, 11)),
            patch("os.close") as mock_close,
            patch("os.fdopen", return_value=fake_file),
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=proc),
            ),
            patch("asyncio.wait_for", side_effect=fake_wait_for),
        ):
            backend = XvfbBackend()
            await backend.start()
            assert backend.display_id() == ":42"
            mock_close.assert_called_with(11)

    @pytest.mark.asyncio
    async def test_start_raises_if_binary_missing(self):
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=FileNotFoundError()),
        ):
            backend = XvfbBackend()
            with pytest.raises(RuntimeError, match="Xvfb binary not found"):
                await backend.start()

    @pytest.mark.asyncio
    async def test_start_raises_on_timeout(self):
        proc = MagicMock()
        proc.terminate = MagicMock()
        proc.wait = AsyncMock(return_value=0)

        fake_file = MagicMock()
        fake_file.__enter__ = MagicMock(return_value=fake_file)
        fake_file.__exit__ = MagicMock(return_value=False)

        with (
            patch("os.pipe", return_value=(10, 11)),
            patch("os.close"),
            patch("os.fdopen", return_value=fake_file),
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=proc),
            ),
            patch(
                "asyncio.wait_for",
                new=AsyncMock(side_effect=asyncio.TimeoutError()),
            ),
        ):
            backend = XvfbBackend(timeout=0.1)
            with pytest.raises(RuntimeError, match="did not become ready"):
                await backend.start()
            assert backend.display_id() is None
            proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_terminates_process(self):
        proc = MagicMock()
        proc.terminate = MagicMock()
        proc.wait = AsyncMock(return_value=0)

        backend = XvfbBackend()
        backend._proc = proc
        backend._display_id = ":99"

        await backend.stop()
        proc.terminate.assert_called_once()
        assert backend._proc is None
        assert backend.display_id() is None

    @pytest.mark.asyncio
    async def test_stop_noop_when_not_started(self):
        backend = XvfbBackend()
        await backend.stop()


class TestXvfbContextManager:
    @pytest.mark.asyncio
    async def test_yields_display_id_and_stops(self):
        proc = MagicMock()
        proc.terminate = MagicMock()
        proc.wait = AsyncMock(return_value=0)

        fake_file = MagicMock()
        fake_file.__enter__ = MagicMock(return_value=fake_file)
        fake_file.__exit__ = MagicMock(return_value=False)

        async def fake_wait_for(coro, *, timeout):
            return "55\n"

        with (
            patch("os.pipe", return_value=(10, 11)),
            patch("os.close"),
            patch("os.fdopen", return_value=fake_file),
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=proc),
            ),
            patch("asyncio.wait_for", side_effect=fake_wait_for),
        ):
            async with xvfb() as display_id:
                assert display_id == ":55"

            proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_stops_on_exception(self):
        proc = MagicMock()
        proc.terminate = MagicMock()
        proc.wait = AsyncMock(return_value=0)

        fake_file = MagicMock()
        fake_file.__enter__ = MagicMock(return_value=fake_file)
        fake_file.__exit__ = MagicMock(return_value=False)

        async def fake_wait_for(coro, *, timeout):
            return "10\n"

        with (
            patch("os.pipe", return_value=(10, 11)),
            patch("os.close"),
            patch("os.fdopen", return_value=fake_file),
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=proc),
            ),
            patch("asyncio.wait_for", side_effect=fake_wait_for),
        ):
            with pytest.raises(ValueError):
                async with xvfb():
                    raise ValueError("boom")

            proc.terminate.assert_called_once()
