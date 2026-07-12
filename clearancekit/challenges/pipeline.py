"""The ChallengePipeline runner."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clearancekit.display.backend import DisplayBackend

from clearancekit.challenges.detectors import (
    ChallengeDetector,
    DOMDetector,
)
from clearancekit.challenges.solvers import (
    ChallengeSolver,
    OSClickSolver,
    PassiveWaitSolver,
)
from clearancekit.challenges.types import (
    AggregateStrategy,
    CFPassResult,
    ChallengeKind,
    DetectionVote,
)
from clearancekit.errors import CFBlocked, CFTimeout
from clearancekit.transports.base import BrowserDriver

log = logging.getLogger(__name__)

# Priority for tie-breaking and "any" strategy:
# BLOCKED > INTERACTIVE > PASSIVE > UNKNOWN > NONE
_KIND_PRIORITY: dict[ChallengeKind, int] = {
    ChallengeKind.CF_BLOCKED: 4,
    ChallengeKind.CF_INTERACTIVE: 3,
    ChallengeKind.CF_PASSIVE: 2,
    ChallengeKind.UNKNOWN: 1,
    ChallengeKind.NONE: 0,
}


def _aggregate(
    votes: list[DetectionVote], *, strategy: AggregateStrategy
) -> ChallengeKind:
    """Combine multiple votes into a single decision.

    - ``CF_BLOCKED`` always wins regardless of strategy.
    - ``MAJORITY``: most-voted kind; ties broken by ``_KIND_PRIORITY``.
    - ``ANY``: highest-priority kind (so any non-NONE wins over NONE).
    - ``WEIGHTED``: sum of confidences per kind; highest wins; ties → priority.
    """
    if any(v.kind == ChallengeKind.CF_BLOCKED for v in votes):
        return ChallengeKind.CF_BLOCKED
    if not votes:
        return ChallengeKind.NONE

    if strategy is AggregateStrategy.ANY:
        return max((v.kind for v in votes), key=lambda k: _KIND_PRIORITY[k])

    if strategy is AggregateStrategy.WEIGHTED:
        bucket: dict[ChallengeKind, float] = {}
        for v in votes:
            bucket[v.kind] = bucket.get(v.kind, 0.0) + v.confidence
        return max(bucket, key=lambda k: (bucket[k], _KIND_PRIORITY[k]))

    # Default: majority vote.
    counter: Counter[ChallengeKind] = Counter(v.kind for v in votes)
    return max(counter, key=lambda k: (counter[k], _KIND_PRIORITY[k]))


class ChallengePipeline:
    """Detect-and-solve loop until ``NONE``, timeout, or hard block."""

    def __init__(
        self,
        *,
        detectors: list[ChallengeDetector] | None = None,
        solvers: list[ChallengeSolver] | None = None,
        max_wait_seconds: float = 30.0,
        poll_interval_seconds: float = 1.0,
        aggregate_strategy: AggregateStrategy = AggregateStrategy.MAJORITY,
        debug_dir: Path | None = None,
    ) -> None:
        self._detectors: list[ChallengeDetector] = list(
            detectors or [DOMDetector()]
        )
        self._solvers: list[ChallengeSolver] = list(
            solvers
            or [
                PassiveWaitSolver(),
                OSClickSolver(),
            ]
        )
        self._max_wait = max_wait_seconds
        self._poll = poll_interval_seconds
        self._strategy = aggregate_strategy

    async def run(
        self, driver: BrowserDriver, *, display: DisplayBackend | None = None
    ) -> CFPassResult:
        """Run the detect-and-solve loop until pass, timeout, or hard block.

        Args:
            driver: Browser driver for page inspection.
            display: DisplayBackend for screen capture / click targeting.
                Passed to solvers that need it (e.g. OSClickSolver).

        Returns:
            CFPassResult on successful challenge resolution.

        Raises:
            CFTimeout: Loop ran for ``max_wait_seconds`` without passing.
            CFBlocked: A detector reported a hard Cloudflare block.
        """
        display_id = display.display_id() if display else None
        votes_history: list[list[DetectionVote]] = []
        iterations = 0
        t0 = time.monotonic()

        # Main polling loop — runs until one of the three exits fires.
        while time.monotonic() - t0 < self._max_wait:
            iterations += 1

            # Phase 1: Detect — run detectors sequentially.
            # nodriver's CDP transaction system cannot tolerate task
            # cancellation, so we avoid gather/wait_for entirely.
            votes: list[DetectionVote] = []
            for detector in self._detectors:
                votes.append(await detector.detect(driver))
            votes_history.append(votes)

            # Phase 2: Aggregate — combine votes into a single decision.
            # CF_BLOCKED has veto power (one vote = blocked regardless).
            kind = _aggregate(votes, strategy=self._strategy)

            log.debug(
                "[iter %d] votes=%s → kind=%s",
                iterations,
                [(v.detector_name, v.kind.value, v.confidence) for v in votes],
                kind.value,
            )

            # Exit: challenge resolved — page is clean.
            if kind == ChallengeKind.NONE:
                log.info(
                    "CF passed in %.2fs (%d iterations)",
                    time.monotonic() - t0,
                    iterations,
                )
                return CFPassResult(
                    passed=True,
                    elapsed_s=time.monotonic() - t0,
                    iterations=iterations,
                    votes_history=votes_history,
                )

            # Exit: hard block — Cloudflare won't let us through.
            if kind == ChallengeKind.CF_BLOCKED:
                log.warning("CF hard block detected at iteration %d", iterations)
                raise CFBlocked(
                    "Cloudflare hard block",
                    iterations=iterations,
                    votes=votes,
                )

            # Phase 3: Solve — try matching solvers in order until one succeeds.
            for solver in self._solvers:
                if kind not in solver.handles:
                    continue
                log.debug("[iter %d] running solver %s", iterations, solver.name)
                result = await solver.solve(driver, kind, display=display_id)
                log.debug(
                    "[iter %d] solver %s → success=%s",
                    iterations,
                    solver.name,
                    result.success,
                )
                if result.success:
                    break
            else:
                log.debug(
                    "[iter %d] no solver succeeded for %s",
                    iterations,
                    kind.value,
                )

            # Throttle before next detection cycle.
            if self._poll > 0:
                await asyncio.sleep(self._poll)

        # Exit: timeout — but if cf_clearance exists, treat as partial pass.
        cookies = await driver.get_cookies()
        has_cf = any(c.name == "cf_clearance" for c in cookies)
        if has_cf:
            elapsed = time.monotonic() - t0
            log.warning(
                "Pipeline timeout after %.2fs (%d iters)"
                " but cf_clearance exists — partial pass",
                elapsed,
                iterations,
            )
            return CFPassResult(
                passed=True,
                elapsed_s=elapsed,
                iterations=iterations,
                votes_history=votes_history,
            )
        raise CFTimeout(
            "ChallengePipeline.run timeout",
            iterations=iterations,
            votes_history=votes_history,
        )
