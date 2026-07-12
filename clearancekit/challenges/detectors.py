"""Built-in CF challenge detectors.

Detectors are stateless and side-effect-free (they only read driver state).
They MAY raise a ``CFError`` subclass to short-circuit the pipeline; this
is the recommended way for site-specific detectors to report
"this isn't a CF problem, it's our own login wall" etc.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from clearancekit.challenges.constants import (
    CF_IFRAME_SRC,
    INTERACTIVE_TEXTS,
    SUCCESS_TEXTS,
    VERIFYING_TEXTS,
)
from clearancekit.challenges.types import ChallengeKind, DetectionVote
from clearancekit.transports.base import BrowserDriver

log = logging.getLogger(__name__)


@runtime_checkable
class ChallengeDetector(Protocol):
    """One vote in a multi-detector consensus."""

    name: str

    async def detect(self, driver: BrowserDriver) -> DetectionVote:
        """Inspect ``driver`` and return this detector's vote on the page kind."""
        ...


class DOMDetector:
    """Probe CF challenge state via CDP DOM walk and OOPIF iframe text."""

    name = "dom"

    async def detect(self, driver: BrowserDriver) -> DetectionVote:
        """Probe for CF iframe via OOPIF target, read its body text."""
        iframe = await driver.find_iframe(CF_IFRAME_SRC)
        if iframe is not None:
            text = iframe.text
            log.debug(
                "[dom] iframe src=%s text=%r",
                iframe.src[:60],
                text,
            )
            if text:
                if any(k in text for k in INTERACTIVE_TEXTS):
                    return DetectionVote(
                        detector_name=self.name,
                        kind=ChallengeKind.CF_INTERACTIVE,
                        confidence=1.0,
                    )
                if any(k in text for k in VERIFYING_TEXTS):
                    return DetectionVote(
                        detector_name=self.name,
                        kind=ChallengeKind.CF_PASSIVE,
                        confidence=0.9,
                    )
                if any(k in text for k in SUCCESS_TEXTS):
                    return DetectionVote(
                        detector_name=self.name,
                        kind=ChallengeKind.NONE,
                        confidence=1.0,
                    )
            is_turnstile = "turnstile" in iframe.src
            log.debug(
                "[dom] iframe text inconclusive, turnstile=%s",
                is_turnstile,
            )
            kind = (
                ChallengeKind.CF_INTERACTIVE
                if is_turnstile
                else ChallengeKind.CF_PASSIVE
            )
            return DetectionVote(
                detector_name=self.name,
                kind=kind,
                confidence=0.7,
            )

        has_form = await driver.evaluate(
            "!!document.querySelector("
            "'#challenge-form, #challenge-running,"
            " #challenge-stage')"
        )
        if has_form:
            log.debug("[dom] challenge form found → cf_passive")
            return DetectionVote(
                detector_name=self.name,
                kind=ChallengeKind.CF_PASSIVE,
                confidence=0.85,
            )

        has_cf_opt = await driver.evaluate("!!window._cf_chl_opt")
        if has_cf_opt:
            log.debug("[dom] _cf_chl_opt present → cf_passive")
            return DetectionVote(
                detector_name=self.name,
                kind=ChallengeKind.CF_PASSIVE,
                confidence=0.7,
            )

        log.debug("[dom] no indicators → none")
        return DetectionVote(
            detector_name=self.name,
            kind=ChallengeKind.NONE,
            confidence=0.7,
        )
