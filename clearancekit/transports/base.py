"""Browser driver Protocols and transport-level dataclasses.

The composite ``BrowserDriver`` is what ``Session`` depends on. Sub-protocols
exist so users implementing custom drivers (or detectors/solvers needing a
narrower contract) can depend on just what they need.

Dataclasses defined here (``Cookie``, ``FetchOptions``, ``FetchResult``,
``NavigateResult``) form the transport contract — they are part of the
Protocol signatures. Session-level code defines its own result types for
the public API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from clearancekit.display.backend import DisplayBackend


@dataclass(kw_only=True, slots=True, frozen=True)
class Cookie:
    """Browser cookie, mirrors CDP ``Network.Cookie`` minus internals."""

    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = False
    http_only: bool = False
    same_site: str | None = None
    expires: float | None = None


@dataclass(kw_only=True, slots=True)
class FetchOptions:
    """Options for in-browser fetch.

    ``body`` and ``form`` are mutually exclusive — if both are set,
    ``form`` takes precedence (urlencoded, ``Content-Type`` auto-set).
    ``body`` must be text; binary bodies are corrupted by UTF-8 replace.
    """

    method: str = "GET"
    headers: dict[str, str] | None = None
    body: str | bytes | None = None
    form: dict[str, str] | None = None
    follow_redirects: bool = True
    timeout: float = 20.0


@dataclass(kw_only=True, slots=True, frozen=True)
class FetchResult:
    """Response from an in-browser fetch. Body is text-only (UTF-8)."""

    status: int
    final_url: str
    headers: dict[str, str]
    body: str
    elapsed_ms: int


@dataclass(kw_only=True, slots=True, frozen=True)
class NavigateResult:
    """Result of a browser navigation at the transport layer.

    ``headers`` are the main-frame document response headers captured at
    the network layer (CDP ``Network.responseReceived``).
    """

    final_url: str
    headers: dict[str, str]


@runtime_checkable
class Navigator(Protocol):
    """Page navigation."""

    async def navigate(
        self, url: str, *, headers: dict[str, str] | None = None,
    ) -> None:
        """Load ``url`` in the current tab. Discards in-flight JS context.

        Returns once the document has finished loading. Read the result with
        :meth:`response_meta` (URL + headers) and :meth:`content` (body) *after*
        the CF pipeline has run.

        ``headers`` are extra HTTP headers injected via CDP
        ``Network.setExtraHTTPHeaders`` for the navigation request (e.g.
        ``Authorization``). They are cleared after the page load completes.
        """
        ...

    def response_meta(self) -> NavigateResult:
        """Final URL + response headers of the latest :meth:`navigate`.

        Returns the final main-frame document result, post-CF.
        """
        ...

    async def content(self) -> str | None:
        """Body of the latest :meth:`navigate`, on demand.

        Returns the downloaded file if it became a download, else the
        document's raw response body (falling back to rendered DOM text).
        ``None`` if unavailable.
        """
        ...


@runtime_checkable
class JSExecutor(Protocol):
    """Arbitrary JS execution in the current tab."""

    async def evaluate(
        self,
        js: str,
        *,
        await_promise: bool = False,
    ) -> Any:
        """Run ``js`` in the page context, return its value."""
        ...


@runtime_checkable
class Fetcher(Protocol):
    """Same-origin, text-only HTTP from inside the browser tab.

    Cross-origin or binary bodies are NOT supported by this contract; the
    builtin nodriver implementation forces both restrictions to keep the
    bypass guarantee (Cloudflare validates JA3 + cookies of the
    requesting tab, so only XHR-from-tab works).
    """

    async def fetch(self, url: str, *, opts: FetchOptions | None = None) -> FetchResult:
        """Issue an XHR-from-tab request and return the parsed result."""
        ...

    async def get_cookies(self, *, host: str | None = None) -> list[Cookie]:
        """Return cookies for ``host`` (or all cookies if ``host`` is None)."""
        ...


@runtime_checkable
class Screenshotable(Protocol):
    """Tab screenshot capability."""

    async def screenshot(self) -> bytes:
        """Return PNG bytes of the current tab viewport."""
        ...


@dataclass(kw_only=True, slots=True, frozen=True)
class ViewportRect:
    """Element position in viewport coordinates."""

    x: float
    y: float
    width: float
    height: float


@dataclass(kw_only=True, slots=True, frozen=True)
class IframeInfo:
    """Iframe discovered via OOPIF targets + CDP DOM walk."""

    src: str
    rect: ViewportRect
    text: str | None = None


@runtime_checkable
class ElementInteractor(Protocol):
    """Element finding and iframe inspection.

    iframe lookup uses OOPIF target discovery + DOM pierce for position
    and target attachment for content reading.
    """

    async def find_text_and_click(
        self, text: str, *, timeout: float = 10.0
    ) -> bool:
        """Find element containing ``text`` (searches across all frames), CDP-click it.

        Returns True if found and clicked, False otherwise.
        """
        ...

    async def find_iframe(self, src_contains: str) -> IframeInfo | None:
        """Find an OOPIF iframe whose URL contains the given string.

        Discovers the target via ``target.getTargets()``, reads its
        visible text via OOPIF attachment, and gets position via DOM
        walk + box model.  Returns ``IframeInfo`` with src, rect,
        and text, or ``None`` if not found.
        """
        ...


@runtime_checkable
class BrowserDriver(
    Navigator, JSExecutor, Fetcher, Screenshotable,
    ElementInteractor,
    Protocol,
):
    """Full browser driver: composition of the sub-protocols + lifecycle.

    Implementations: ``clearancekit.transports.nodriver.NodriverDriver``.
    """

    async def start(self, *, display: DisplayBackend | None = None) -> None:
        """Launch the browser process.

        Args:
            display: DisplayBackend instance. If provided, uses its
                display_id() for DISPLAY env and screen_size() for
                window dimensions. None = use environment default with
                fallback 1920x1080.

        Raises:
            RuntimeError: If browser binary is missing or launch fails.
        """
        ...

    async def close(self) -> None:
        """Tear down the browser process and free resources."""
        ...

    def is_started(self) -> bool:
        """Whether the browser process is running."""
        ...
