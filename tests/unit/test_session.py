"""Tests for Session class + module-level session() helper."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clearancekit.errors import CFSessionDead
from clearancekit.transports.base import FetchResult as TransportFetchResult
from clearancekit.transports.base import NavigateResult as TransportNavigateResult


@pytest.fixture
def mock_browser():
    d = MagicMock()
    d.is_started = MagicMock(return_value=True)
    d.start = AsyncMock()
    d.navigate = AsyncMock()
    d.response_meta = MagicMock(
        return_value=TransportNavigateResult(final_url="https://x/", headers={})
    )
    d.content = AsyncMock(return_value="ok")
    d.evaluate = AsyncMock(return_value=None)
    d.fetch = AsyncMock(
        return_value=TransportFetchResult(
            status=200,
            final_url="https://x/",
            headers={},
            body="ok",
            elapsed_ms=1,
        )
    )
    d.get_cookies = AsyncMock(return_value=[])
    d.screenshot = AsyncMock(return_value=b"PNG")
    d.close = AsyncMock()
    return d


@pytest.fixture
def mock_pipeline():
    from clearancekit.challenges.types import CFPassResult

    p = MagicMock()
    p.run = AsyncMock(
        return_value=CFPassResult(
            passed=True,
            elapsed_s=0.1,
            iterations=1,
        )
    )
    return p


class TestSessionDelegation:
    @pytest.mark.asyncio
    async def test_navigate_runs_pipeline(self, mock_browser, mock_pipeline):
        from clearancekit.session import Session

        s = Session(browser=mock_browser, pipeline=mock_pipeline)
        await s.navigate("https://x")
        mock_browser.navigate.assert_called_once_with("https://x", headers=None)
        mock_pipeline.run.assert_called_once_with(mock_browser, display=None)

    @pytest.mark.asyncio
    async def test_fetch_delegates(self, mock_browser, mock_pipeline):
        from clearancekit.session import Session

        s = Session(browser=mock_browser, pipeline=mock_pipeline)
        r = await s.fetch("https://x")
        assert r.body == "ok"

    @pytest.mark.asyncio
    async def test_evaluate_delegates(self, mock_browser, mock_pipeline):
        from clearancekit.session import Session

        s = Session(browser=mock_browser, pipeline=mock_pipeline)
        await s.evaluate("1+1")
        mock_browser.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_cookies_delegates(self, mock_browser, mock_pipeline):
        from clearancekit.session import Session

        s = Session(browser=mock_browser, pipeline=mock_pipeline)
        await s.get_cookies(host="x")
        mock_browser.get_cookies.assert_called_once_with(host="x")

    @pytest.mark.asyncio
    async def test_screenshot_delegates(self, mock_browser, mock_pipeline):
        from clearancekit.session import Session

        s = Session(browser=mock_browser, pipeline=mock_pipeline)
        b = await s.screenshot()
        assert b == b"PNG"

    @pytest.mark.asyncio
    async def test_refresh_cf_invokes_pipeline(self, mock_browser, mock_pipeline):
        from clearancekit.session import Session

        s = Session(browser=mock_browser, pipeline=mock_pipeline)
        r = await s.refresh_cf()
        assert r.passed is True
        mock_pipeline.run.assert_called_once_with(mock_browser, display=None)

    @pytest.mark.asyncio
    async def test_session_dead_propagates(self, mock_browser, mock_pipeline):
        from clearancekit.session import Session

        mock_browser.fetch.side_effect = CFSessionDead("dead")
        s = Session(browser=mock_browser, pipeline=mock_pipeline)
        with pytest.raises(CFSessionDead):
            await s.fetch("https://x")

    @pytest.mark.asyncio
    async def test_async_context_manager_closes(self, mock_browser, mock_pipeline):
        from clearancekit.session import Session

        async with Session(browser=mock_browser, pipeline=mock_pipeline) as s:
            assert s is not None
        mock_browser.close.assert_called_once()


class TestSessionCreate:
    @pytest.mark.asyncio
    async def test_create_starts_browser_if_not_started(
        self,
        mock_browser,
        mock_pipeline,
    ):
        from clearancekit.session import Session

        mock_browser.is_started.return_value = False

        with patch(
            "clearancekit.session.ChallengePipeline",
            return_value=mock_pipeline,
        ):
            await Session.create(
                browser=mock_browser,
                warmup_url="https://x/",
            )
            mock_browser.start.assert_called_once_with(display=None)
            mock_browser.navigate.assert_called_once_with("https://x/")
            mock_pipeline.run.assert_called_once_with(mock_browser, display=None)

    @pytest.mark.asyncio
    async def test_create_skips_start_if_already_started(
        self,
        mock_browser,
        mock_pipeline,
    ):
        from clearancekit.session import Session

        mock_browser.is_started.return_value = True

        with patch(
            "clearancekit.session.ChallengePipeline",
            return_value=mock_pipeline,
        ):
            await Session.create(
                browser=mock_browser,
                warmup_url="https://x/",
            )
            mock_browser.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_uses_provided_pipeline(
        self,
        mock_browser,
        mock_pipeline,
    ):
        from clearancekit.session import Session

        s = await Session.create(
            browser=mock_browser,
            pipeline=mock_pipeline,
            warmup_url="https://x/",
        )
        mock_pipeline.run.assert_called_once_with(mock_browser, display=None)
        assert s._pipeline is mock_pipeline

    @pytest.mark.asyncio
    async def test_create_builds_default_pipeline_when_none(
        self,
        mock_browser,
        mock_pipeline,
    ):
        from clearancekit.session import Session

        with patch(
            "clearancekit.session.ChallengePipeline",
            return_value=mock_pipeline,
        ) as mock_cls:
            await Session.create(
                browser=mock_browser,
                warmup_url="https://x/",
            )
            mock_cls.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_create_starts_display_if_not_started(
        self,
        mock_browser,
        mock_pipeline,
    ):
        from clearancekit.session import Session

        mock_browser.is_started.return_value = False
        mock_display = MagicMock()
        mock_display.display_id = MagicMock(side_effect=[None, ":99"])
        mock_display.start = AsyncMock()
        mock_display.stop = AsyncMock()

        with patch(
            "clearancekit.session.ChallengePipeline",
            return_value=mock_pipeline,
        ):
            await Session.create(
                browser=mock_browser,
                display=mock_display,
                warmup_url="https://x/",
            )
            mock_display.start.assert_called_once()
            mock_browser.start.assert_called_once_with(
                display=mock_display,
            )

    @pytest.mark.asyncio
    async def test_create_passes_display_to_pipeline_run(
        self,
        mock_browser,
        mock_pipeline,
    ):
        from clearancekit.session import Session

        mock_display = MagicMock()
        mock_display.display_id = MagicMock(return_value=":55")

        with patch(
            "clearancekit.session.ChallengePipeline",
            return_value=mock_pipeline,
        ):
            await Session.create(
                browser=mock_browser,
                display=mock_display,
                warmup_url="https://x/",
            )
            mock_pipeline.run.assert_called_once_with(
                mock_browser, display=mock_display
            )

    @pytest.mark.asyncio
    async def test_close_stops_display(self, mock_browser, mock_pipeline):
        from clearancekit.session import Session

        mock_display = MagicMock()
        mock_display.display_id = MagicMock(return_value=":10")
        mock_display.stop = AsyncMock()

        s = Session(browser=mock_browser, pipeline=mock_pipeline, display=mock_display)
        await s.close()
        mock_display.stop.assert_called_once()


class TestSessionHelper:
    @pytest.mark.asyncio
    async def test_helper_creates_and_closes(self, mock_browser, mock_pipeline):
        from clearancekit.session import session

        with patch(
            "clearancekit.session.ChallengePipeline",
            return_value=mock_pipeline,
        ):
            async with session(
                browser=mock_browser,
                warmup_url="https://x/",
            ) as s:
                assert s is not None
            mock_browser.close.assert_called_once()
