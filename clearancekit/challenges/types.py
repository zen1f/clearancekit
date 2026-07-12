"""Types specific to the challenge pipeline (detectors, solvers, results)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AggregateStrategy(str, Enum):
    """How detector votes are combined into a single decision."""

    MAJORITY = "majority"
    ANY = "any"
    WEIGHTED = "weighted"


class ChallengeKind(str, Enum):
    """What the page currently is.

    .. note::
       Detectors that need to report site-specific blockers not modeled
       here (e.g. a target's login wall) should raise a ``CFError``
       subclass instead — this aborts the pipeline cleanly and propagates
       to the caller.
    """

    NONE = "none"  # not a challenge; pipeline returns
    CF_PASSIVE = "cf_passive"  # "Just a moment..."
    CF_INTERACTIVE = "cf_interactive"  # Turnstile checkbox
    CF_BLOCKED = "cf_blocked"  # WAF 1020 hard block
    UNKNOWN = "unknown"  # detector can't tell; aggregator may treat as NONE


@dataclass(kw_only=True, slots=True, frozen=True)
class DetectionVote:
    """One detector's verdict for the current page state."""

    detector_name: str
    kind: ChallengeKind
    confidence: float  # 0.0–1.0


@dataclass(kw_only=True, slots=True, frozen=True)
class SolveResult:
    """Outcome of a single ``solver.solve()`` call. Diagnostic-only.

    The pipeline does not branch on ``success`` — it always re-detects.
    Used for logging / debugging.
    """

    success: bool
    solver_name: str
    elapsed_s: float
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True, slots=True, frozen=True)
class CFPassResult:
    """Return value of ``ChallengePipeline.run()``."""

    passed: bool
    elapsed_s: float
    iterations: int
    votes_history: list[list[DetectionVote]] = field(default_factory=list)
