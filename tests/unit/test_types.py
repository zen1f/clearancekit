"""Tests for transport-level and session-level dataclasses."""

from clearancekit.session import FetchResult, NavigateResult
from clearancekit.transports.base import Cookie, FetchOptions
from clearancekit.transports.base import FetchResult as TransportFetchResult


class TestCookie:
    def test_required_fields(self):
        c = Cookie(name="cf_clearance", value="xyz", domain=".example.com")
        assert c.name == "cf_clearance"
        assert c.value == "xyz"
        assert c.domain == ".example.com"
        assert c.path == "/"  # default
        assert c.secure is False
        assert c.http_only is False
        assert c.same_site is None
        assert c.expires is None


class TestFetchOptions:
    def test_defaults(self):
        o = FetchOptions()
        assert o.method == "GET"
        assert o.headers is None
        assert o.body is None
        assert o.form is None
        assert o.follow_redirects is True
        assert o.timeout == 20.0

    def test_custom(self):
        o = FetchOptions(method="POST", body="x", timeout=5.0)
        assert o.method == "POST"
        assert o.body == "x"
        assert o.timeout == 5.0


class TestTransportFetchResult:
    def test_required_fields(self):
        r = TransportFetchResult(
            status=200,
            final_url="https://x.com/api",
            headers={"Content-Type": "application/json"},
            body='{"ok":true}',
            elapsed_ms=123,
        )
        assert r.status == 200
        assert r.body == '{"ok":true}'
        assert r.elapsed_ms == 123


class TestSessionFetchResult:
    def test_required_fields(self):
        r = FetchResult(
            status=200,
            final_url="https://x.com/api",
            headers={"Content-Type": "application/json"},
            body='{"ok":true}',
            elapsed_ms=123,
        )
        assert r.status == 200
        assert r.body == '{"ok":true}'
        assert r.elapsed_ms == 123


class TestSessionNavigateResult:
    def test_required_fields(self):
        r = NavigateResult(
            final_url="https://example.com/page",
            headers={"content-type": "text/html"},
        )
        assert r.final_url == "https://example.com/page"
        assert r.headers == {"content-type": "text/html"}


def test_no_session_health_exported():
    """Per spec: SessionHealth is intentionally removed (Pure EAFP)."""
    import clearancekit.transports.base as m

    assert not hasattr(m, "SessionHealth")
    assert not hasattr(m, "SessionState")
