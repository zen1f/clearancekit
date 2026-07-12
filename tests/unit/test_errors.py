"""Tests for clearancekit.errors hierarchy."""

import pytest

from clearancekit.errors import (
    CFAutoClickUnsupported,
    CFBlocked,
    CFCookieExpired,
    CFError,
    CFFetchFailed,
    CFInteractiveBlocked,
    CFSessionDead,
    CFTimeout,
)


class TestCFErrorBase:
    def test_inherits_exception(self):
        assert issubclass(CFError, Exception)

    def test_carries_context_dict(self):
        e = CFError("boom", url="https://x.com", status=503)
        assert str(e) == "boom"
        assert e.context == {"url": "https://x.com", "status": 503}

    def test_empty_context_by_default(self):
        e = CFError("boom")
        assert e.context == {}


@pytest.mark.parametrize(
    "cls",
    [
        CFTimeout,
        CFFetchFailed,
        CFSessionDead,
        CFAutoClickUnsupported,
        CFInteractiveBlocked,
        CFBlocked,
        CFCookieExpired,
    ],
)
class TestSubclasses:
    def test_inherits_cferror(self, cls):
        assert issubclass(cls, CFError)

    def test_carries_context(self, cls):
        e = cls("msg", foo="bar")
        assert e.context == {"foo": "bar"}


def test_distinct_subclasses_not_related():
    assert not issubclass(CFTimeout, CFFetchFailed)
    assert not issubclass(CFBlocked, CFCookieExpired)
