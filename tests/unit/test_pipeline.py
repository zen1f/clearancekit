"""Tests for ChallengePipeline.run (incl. fallback chain semantics)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from clearancekit.challenges.pipeline import ChallengePipeline, _aggregate
from clearancekit.challenges.types import (
    AggregateStrategy,
    ChallengeKind,
    DetectionVote,
    SolveResult,
)
from clearancekit.errors import CFBlocked, CFTimeout


class FakeDetector:
    def __init__(self, name, vote_sequence):
        self.name = name
        self._seq = list(vote_sequence)
        self._i = 0

    async def detect(self, driver):
        v = self._seq[min(self._i, len(self._seq) - 1)]
        self._i += 1
        return DetectionVote(detector_name=self.name, kind=v, confidence=1.0)


class FakeSolver:
    def __init__(self, name, kinds, succeeds=True):
        self.name = name
        self.handles = set(kinds)
        self.calls = 0
        self._succeeds = succeeds

    async def solve(self, driver, kind, *, display=None):
        self.calls += 1
        return SolveResult(
            success=self._succeeds, solver_name=self.name, elapsed_s=0.01
        )


class TestAggregate:
    def test_majority_wins(self):
        votes = [
            DetectionVote(
                detector_name="a",
                kind=ChallengeKind.CF_PASSIVE,
                confidence=1.0,
            ),
            DetectionVote(
                detector_name="b",
                kind=ChallengeKind.CF_PASSIVE,
                confidence=1.0,
            ),
            DetectionVote(
                detector_name="c",
                kind=ChallengeKind.NONE,
                confidence=1.0,
            ),
        ]
        result = _aggregate(votes, strategy=AggregateStrategy.MAJORITY)
        assert result == ChallengeKind.CF_PASSIVE

    def test_any_picks_non_none_with_priority(self):
        votes = [
            DetectionVote(
                detector_name="a",
                kind=ChallengeKind.NONE,
                confidence=1.0,
            ),
            DetectionVote(
                detector_name="b",
                kind=ChallengeKind.CF_INTERACTIVE,
                confidence=1.0,
            ),
        ]
        result = _aggregate(votes, strategy=AggregateStrategy.ANY)
        assert result == ChallengeKind.CF_INTERACTIVE

    def test_blocked_always_wins(self):
        votes = [
            DetectionVote(
                detector_name="a",
                kind=ChallengeKind.NONE,
                confidence=1.0,
            ),
            DetectionVote(
                detector_name="b",
                kind=ChallengeKind.CF_BLOCKED,
                confidence=0.6,
            ),
        ]
        for strategy in AggregateStrategy:
            assert _aggregate(votes, strategy=strategy) == ChallengeKind.CF_BLOCKED


class TestPipelineRun:
    @pytest.mark.asyncio
    async def test_returns_immediately_when_none(self):
        p = ChallengePipeline(
            poll_interval_seconds=0.0,
            max_wait_seconds=5.0,
            detectors=[FakeDetector("d", [ChallengeKind.NONE])],
            solvers=[FakeSolver("s", {ChallengeKind.CF_PASSIVE})],
        )
        r = await p.run(MagicMock())
        assert r.passed is True
        assert r.iterations == 1

    @pytest.mark.asyncio
    async def test_passive_solver_used_then_pass(self):
        det = FakeDetector("d", [ChallengeKind.CF_PASSIVE, ChallengeKind.NONE])
        sol = FakeSolver("s", {ChallengeKind.CF_PASSIVE})
        p = ChallengePipeline(
            poll_interval_seconds=0.0,
            max_wait_seconds=5.0,
            detectors=[det],
            solvers=[sol],
        )
        r = await p.run(MagicMock())
        assert r.passed is True
        assert sol.calls == 1

    @pytest.mark.asyncio
    async def test_blocked_raises_immediately(self):
        det = FakeDetector("d", [ChallengeKind.CF_BLOCKED])
        p = ChallengePipeline(
            poll_interval_seconds=0.0,
            max_wait_seconds=5.0,
            detectors=[det],
            solvers=[],
        )
        with pytest.raises(CFBlocked):
            await p.run(MagicMock())

    @pytest.mark.asyncio
    async def test_timeout(self):
        det = FakeDetector("d", [ChallengeKind.CF_PASSIVE])  # never resolves
        sol = FakeSolver("s", {ChallengeKind.CF_PASSIVE})
        p = ChallengePipeline(
            poll_interval_seconds=0.01,
            max_wait_seconds=0.05,
            detectors=[det],
            solvers=[sol],
        )
        driver = MagicMock()
        driver.get_cookies = AsyncMock(return_value=[])
        with pytest.raises(CFTimeout):
            await p.run(driver)

    @pytest.mark.asyncio
    async def test_solver_retried_across_iterations(self):
        """Same solver is called again if challenge persists."""
        det = FakeDetector(
            "d",
            [
                ChallengeKind.CF_INTERACTIVE,
                ChallengeKind.CF_INTERACTIVE,
                ChallengeKind.NONE,
            ],
        )
        sol = FakeSolver("s", {ChallengeKind.CF_INTERACTIVE})
        p = ChallengePipeline(
            poll_interval_seconds=0.0,
            max_wait_seconds=5.0,
            detectors=[det],
            solvers=[sol],
        )
        r = await p.run(MagicMock())
        assert r.passed is True
        assert sol.calls == 2
