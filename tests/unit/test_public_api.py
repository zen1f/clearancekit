"""Smoke test: all names listed in spec §3.3 are importable from clearancekit."""

import pytest

EXPECTED = [
    # Entry points
    "Session",
    "session",
    # Config
    "DisplayBackend",
    "XvfbBackend",
    # Wire types
    "Cookie",
    "FetchOptions",
    "FetchResult",
    "IframeInfo",
    "NavigateResult",
    # Pipeline & extension types
    "ChallengePipeline",
    "ChallengeKind",
    "CFPassResult",
    "SolveResult",
    "DetectionVote",
    # Protocols
    "BrowserDriver",
    "Navigator",
    "JSExecutor",
    "Fetcher",
    "Screenshotable",
    "ChallengeDetector",
    "ChallengeSolver",
    # Built-in detectors
    "DOMDetector",
    # Built-in solvers
    "PassiveWaitSolver",
    "OSClickSolver",
    # Exceptions
    "CFError",
    "CFTimeout",
    "CFFetchFailed",
    "CFSessionDead",
    "CFInteractiveBlocked",
    "CFAutoClickUnsupported",
    "CFBlocked",
    "CFCookieExpired",
]

REMOVED = [
    "SessionPool",
    "get_pool",
    "SessionState",
    "SessionHealth",
    "DisplayManager",
    "BrowserConfig",
    "ChallengePolicy",
]


@pytest.mark.parametrize("name", EXPECTED)
def test_exported(name):
    import clearancekit as ck

    assert hasattr(ck, name), f"missing public export: {name}"


@pytest.mark.parametrize("name", REMOVED)
def test_not_exported(name):
    import clearancekit as ck

    assert not hasattr(ck, name), f"should NOT be exported: {name}"


def test_version():
    import clearancekit as ck

    assert ck.__version__ == "0.1.0"
