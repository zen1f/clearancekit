"""clearancekit — pluggable Cloudflare bypass via real Chromium."""

from __future__ import annotations

__version__ = "0.1.0"

from clearancekit.challenges.detectors import (
    ChallengeDetector,
    DOMDetector,
)
from clearancekit.challenges.pipeline import ChallengePipeline
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
    SolveResult,
)
from clearancekit.display import DisplayBackend, XvfbBackend
from clearancekit.errors import (
    CFAutoClickUnsupported,
    CFBlocked,
    CFCookieExpired,
    CFError,
    CFFetchFailed,
    CFInteractiveBlocked,
    CFSessionDead,
    CFTimeout,
    DisplayNotSet,
)
from clearancekit.session import FetchResult, NavigateResult, Session, session
from clearancekit.transports.base import (
    BrowserDriver,
    Cookie,
    Fetcher,
    FetchOptions,
    IframeInfo,
    JSExecutor,
    Navigator,
    Screenshotable,
    ViewportRect,
)

__all__ = [
    "__version__",
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
    # Pipeline & types
    "AggregateStrategy",
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
    "ViewportRect",
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
    "DisplayNotSet",
]
