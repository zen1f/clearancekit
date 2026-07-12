"""Tests for clearancekit.challenges.types."""

from clearancekit.challenges.types import (
    CFPassResult,
    ChallengeKind,
    DetectionVote,
    SolveResult,
)


def test_challenge_kind_values():
    assert ChallengeKind.NONE.value == "none"
    assert ChallengeKind.CF_PASSIVE.value == "cf_passive"
    assert ChallengeKind.CF_INTERACTIVE.value == "cf_interactive"
    assert ChallengeKind.CF_BLOCKED.value == "cf_blocked"
    assert ChallengeKind.UNKNOWN.value == "unknown"


def test_detection_vote():
    v = DetectionVote(detector_name="x", kind=ChallengeKind.NONE, confidence=0.9)
    assert v.detector_name == "x"
    assert v.confidence == 0.9


def test_solve_result():
    r = SolveResult(success=True, solver_name="passive_wait", elapsed_s=1.0)
    assert r.success is True
    assert r.detail == {}


def test_cf_pass_result():
    r = CFPassResult(passed=True, elapsed_s=2.0, iterations=3)
    assert r.passed is True
    assert r.votes_history == []
