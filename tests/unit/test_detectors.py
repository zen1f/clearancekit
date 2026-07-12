"""Tests for built-in challenge detectors."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from clearancekit.challenges.detectors import (
    ChallengeDetector,
    DOMDetector,
)
from clearancekit.challenges.types import ChallengeKind
from clearancekit.transports.base import IframeInfo, ViewportRect


def _driver(evaluate_returns=None, cookies=None, iframe=None):
    d = MagicMock()
    if isinstance(evaluate_returns, dict):

        async def fake_eval(js, **kw):
            return evaluate_returns.get(js, None)

        d.evaluate = AsyncMock(side_effect=fake_eval)
    else:
        d.evaluate = AsyncMock(return_value=evaluate_returns)
    d.get_cookies = AsyncMock(return_value=cookies or [])
    d.find_iframe = AsyncMock(return_value=iframe)
    return d


def _iframe(
    src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/xyz",
    text=None,
):
    return IframeInfo(
        src=src,
        rect=ViewportRect(x=100, y=200, width=300, height=65),
        text=text,
    )


class TestDOMDetector:
    @pytest.mark.asyncio
    async def test_turnstile_iframe_with_verify_text_means_interactive(self):
        det = DOMDetector()
        d = _driver(
            iframe=_iframe(text="Verify you are human"),
        )
        v = await det.detect(d)
        assert v.kind == ChallengeKind.CF_INTERACTIVE
        assert v.confidence == 1.0

    @pytest.mark.asyncio
    async def test_iframe_with_verifying_text_means_passive(self):
        det = DOMDetector()
        d = _driver(
            iframe=_iframe(
                text="Verifying that you are not a robot",
            ),
        )
        v = await det.detect(d)
        assert v.kind == ChallengeKind.CF_PASSIVE
        assert v.confidence == 0.9

    @pytest.mark.asyncio
    async def test_iframe_with_chinese_verify_text_means_interactive(self):
        det = DOMDetector()
        d = _driver(
            iframe=_iframe(text="确认您是真人"),
        )
        v = await det.detect(d)
        assert v.kind == ChallengeKind.CF_INTERACTIVE

    @pytest.mark.asyncio
    async def test_iframe_with_success_text_means_none(self):
        det = DOMDetector()
        d = _driver(
            iframe=_iframe(text="Success"),
        )
        v = await det.detect(d)
        assert v.kind == ChallengeKind.NONE
        assert v.confidence == 1.0

    @pytest.mark.asyncio
    async def test_turnstile_iframe_no_text_fallback_interactive(self):
        det = DOMDetector()
        d = _driver(iframe=_iframe())
        v = await det.detect(d)
        assert v.kind == ChallengeKind.CF_INTERACTIVE
        assert v.confidence == 0.7

    @pytest.mark.asyncio
    async def test_managed_iframe_no_text_fallback_passive(self):
        det = DOMDetector()
        d = _driver(
            iframe=_iframe(
                src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/managed",
            ),
        )
        v = await det.detect(d)
        assert v.kind == ChallengeKind.CF_PASSIVE
        assert v.confidence == 0.7

    @pytest.mark.asyncio
    async def test_no_iframe_with_challenge_form_means_passive(self):
        det = DOMDetector()
        d = _driver(evaluate_returns=True)
        v = await det.detect(d)
        assert v.kind == ChallengeKind.CF_PASSIVE

    @pytest.mark.asyncio
    async def test_no_indicators_means_none(self):
        det = DOMDetector()
        v = await det.detect(_driver(evaluate_returns=False))
        assert v.kind == ChallengeKind.NONE

def test_detectors_are_runtime_checkable():
    for det in (DOMDetector(),):
        assert isinstance(det, ChallengeDetector)
