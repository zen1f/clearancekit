"""Sanity that the Protocols are importable and runtime_checkable works."""

from clearancekit.transports.base import (
    BrowserDriver,
    ElementInteractor,
    Fetcher,
    IframeInfo,
    JSExecutor,
    Navigator,
    Screenshotable,
    ViewportRect,
)


def test_protocols_are_runtime_checkable():
    """Each protocol can be isinstance-checked at runtime."""

    class _Dummy:
        async def navigate(self, url, *, headers=None): ...
        def response_meta(self): ...
        async def content(self): ...
        async def evaluate(self, js, *, await_promise=False): ...
        async def fetch(self, url, *, opts=None): ...
        async def get_cookies(self, *, host=None): ...
        async def screenshot(self): ...
        async def start(self, *, display=None): ...
        async def close(self): ...
        def is_started(self):
            return True
        async def find_text_and_click(self, text, *, timeout=10.0): ...
        async def find_iframe(self, src_contains): ...

    d = _Dummy()
    assert isinstance(d, Navigator)
    assert isinstance(d, JSExecutor)
    assert isinstance(d, Fetcher)
    assert isinstance(d, Screenshotable)
    assert isinstance(d, ElementInteractor)
    assert isinstance(d, BrowserDriver)


def test_viewport_rect_fields():
    r = ViewportRect(x=10.0, y=20.0, width=100.0, height=50.0)
    assert r.x == 10.0
    assert r.y == 20.0
    assert r.width == 100.0
    assert r.height == 50.0


def test_iframe_info_fields():
    rect = ViewportRect(x=10.0, y=20.0, width=300.0, height=65.0)
    info = IframeInfo(
        src="https://challenges.cloudflare.com/abc",
        rect=rect,
        text="Verify you are human",
    )
    assert info.src == "https://challenges.cloudflare.com/abc"
    assert info.rect.x == 10.0
    assert info.rect.width == 300.0
    assert info.text == "Verify you are human"


def test_iframe_info_text_defaults_to_none():
    rect = ViewportRect(x=0.0, y=0.0, width=100.0, height=50.0)
    info = IframeInfo(
        src="https://challenges.cloudflare.com/abc",
        rect=rect,
    )
    assert info.text is None
