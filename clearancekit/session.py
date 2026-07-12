"""The user-facing Session object and ``session()`` async context helper.

Design notes:
  - Session == Chrome process. Tab is an internal handle, recreated
    transparently by the driver. Only browser death raises ``CFSessionDead``.
  - ``create()`` is the user-facing async factory. ``__init__`` is internal.
  - ``navigate()`` automatically runs the CF pipeline after page load.
  - clearancekit does NOT provide session pooling — callers compose their
    own dict / cache. See ``examples/caller_managed_pool.py``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from clearancekit.display import DisplayBackend

from clearancekit.challenges.pipeline import ChallengePipeline
from clearancekit.challenges.types import CFPassResult
from clearancekit.transports.base import BrowserDriver, Cookie, FetchOptions

log = logging.getLogger(__name__)


@dataclass(kw_only=True, slots=True, frozen=True)
class NavigateResult:
    """Result of ``Session.navigate()``.

    ``headers`` are the main-frame document response headers captured at the
    network layer (CDP ``Network.responseReceived``), so they include headers
    that page JS cannot read (e.g. ``subscription-userinfo``,
    ``content-disposition``). Empty dict when no document response was observed
    (e.g. ``about:blank`` or a navigation that turned into a download).

    ``headers`` and ``final_url`` reflect the final main-frame document (after
    the CF pipeline). The response body is fetched separately and on demand via
    ``Session.content()`` — it is not part of this result.
    """

    final_url: str
    headers: dict[str, str]


@dataclass(kw_only=True, slots=True, frozen=True)
class FetchResult:
    """Response from ``Session.fetch()``. Body is text-only (UTF-8)."""

    status: int
    final_url: str
    headers: dict[str, str]
    body: str
    elapsed_ms: int


class Session:
    """Cloudflare-bypassed browser session (one Chrome process + CF pipeline)."""

    def __init__(
        self,
        *,
        browser: BrowserDriver,
        pipeline: ChallengePipeline,
        display: DisplayBackend | None = None,
    ) -> None:
        self._browser = browser
        self._pipeline = pipeline
        self._display = display

    @classmethod
    async def create(
        cls,
        *,
        browser: BrowserDriver,
        warmup_url: str,
        pipeline: ChallengePipeline | None = None,
        display: DisplayBackend | None = None,
    ) -> Session:
        """Create a ready-to-use Session.

        Args:
            browser: BrowserDriver instance. If not yet started, Session
                calls ``start()``.
            warmup_url: Anchor URL — the page on which the initial CF
                challenge is solved. Subsequent ``fetch()`` calls must be
                same-origin.
            pipeline: ChallengePipeline instance. If None, a default
                pipeline is constructed internally.
            display: DisplayBackend instance. If provided and not yet started,
                Session calls ``start()``. Session owns the display lifecycle
                (``stop()`` on close).

        Returns:
            A ready-to-use Session.

        Raises:
            CFTimeout: If the initial pipeline run times out.
            CFBlocked: If Cloudflare hard-blocks the warmup page.
            CFSessionDead: If the browser dies during startup.
        """
        if display is not None and display.display_id() is None:
            await display.start()
            log.debug("display started: %s", display.display_id())

        if not browser.is_started():
            await browser.start(display=display)

        if pipeline is None:
            pipeline = ChallengePipeline()

        log.debug("navigating to warmup_url: %s", warmup_url)
        await browser.navigate(warmup_url)
        await pipeline.run(browser, display=display)

        log.debug("session ready")
        return cls(browser=browser, pipeline=pipeline, display=display)

    async def navigate(
        self, url: str, *, headers: dict[str, str] | None = None,
    ) -> NavigateResult:
        """Load ``url`` in the tab and automatically pass CF if triggered.

        Returns the final main-frame document's URL and response headers,
        captured *after* the CF pipeline — so they reflect the real page, not the
        Cloudflare interstitial. The response body is fetched separately via
        :meth:`content` (lazy / on demand).

        ``headers`` are extra HTTP headers injected at the CDP level for the
        navigation (e.g. ``Authorization``). Cleared after the CF pipeline.
        """
        await self._browser.navigate(url, headers=headers)
        await self._pipeline.run(self._browser, display=self._display)
        tr = self._browser.response_meta()
        return NavigateResult(final_url=tr.final_url, headers=tr.headers)

    async def content(self) -> str | None:
        """Return the body of the most recent :meth:`navigate`, on demand.

        For a download it is the captured file contents; otherwise the document's
        raw response body (falling back to rendered DOM text). ``None`` if no
        body is available.
        """
        return await self._browser.content()

    async def evaluate(
        self,
        js: str,
        *,
        await_promise: bool = False,
    ) -> Any:
        """Run JS in the current tab; return its value."""
        return await self._browser.evaluate(js, await_promise=await_promise)

    async def fetch(self, url: str, *, opts: FetchOptions | None = None) -> FetchResult:
        """Same-origin HTTP request from inside the tab. See ``Fetcher`` docstring."""
        tr = await self._browser.fetch(url, opts=opts)
        return FetchResult(
            status=tr.status,
            final_url=tr.final_url,
            headers=tr.headers,
            body=tr.body,
            elapsed_ms=tr.elapsed_ms,
        )

    async def get_cookies(self, *, host: str | None = None) -> list[Cookie]:
        """Cookies from the browser jar; filtered by ``host`` if given."""
        return await self._browser.get_cookies(host=host)

    async def screenshot(self) -> bytes:
        """Capture tab viewport as PNG."""
        return await self._browser.screenshot()

    async def refresh_cf(self) -> CFPassResult:
        """Re-run the CF pipeline on the current tab (no navigation)."""
        return await self._pipeline.run(self._browser, display=self._display)

    async def close(self) -> None:
        """Tear down the browser and display backend."""
        await self._browser.close()
        if self._display is not None:
            await self._display.stop()
            self._display = None

    async def __aenter__(self) -> Session:
        """Enter context: return self (browser already started)."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit context: close the underlying browser regardless of exception."""
        await self.close()


@asynccontextmanager
async def session(
    *,
    browser: BrowserDriver,
    pipeline: ChallengePipeline | None = None,
    display: DisplayBackend | None = None,
    warmup_url: str,
) -> AsyncIterator[Session]:
    """Create a Session and ensure it is closed on context exit.

    Equivalent to::

        s = await Session.create(...)
        try:
            yield s
        finally:
            await s.close()
    """
    s = await Session.create(
        browser=browser,
        pipeline=pipeline,
        display=display,
        warmup_url=warmup_url,
    )
    try:
        yield s
    finally:
        await s.close()
