"""Exception hierarchy for clearancekit.

All public exceptions inherit from `CFError`, allowing callers to catch
everything with a single ``except CFError``. Each exception carries a
``context: dict`` field with diagnostic key-value pairs (url, status,
votes, etc.) — useful for logging without parsing the message string.
"""

from __future__ import annotations

from typing import Any


class CFError(Exception):
    """Base for all clearancekit exceptions.

    Args:
        msg: Human-readable message.
        **context: Arbitrary diagnostic key-value pairs attached to ``.context``.
    """

    def __init__(self, msg: str = "", **context: Any) -> None:
        super().__init__(msg)
        self.context: dict[str, Any] = context


class CFTimeout(CFError):
    """Any operation exceeded its time budget (pipeline / fetch / evaluate)."""


class CFFetchFailed(CFError):
    """Browser ``fetch()`` threw (network / DNS / TLS / JSON parse)."""


class CFSessionDead(CFError):
    """Chrome process died. Session is unusable; create a new one."""


class CFAutoClickUnsupported(CFError):
    """Auto-click solver cannot run (non-Linux / missing xdotool / Wayland)."""


class CFInteractiveBlocked(CFError):
    """``OSClickSolver`` exhausted retries without solving."""


class CFBlocked(CFError):
    """Cloudflare WAF hard-block (e.g., error 1020). Not recoverable."""


class CFCookieExpired(CFError):
    """``cf_clearance`` cookie expired. Recover with ``Session.refresh_cf()``."""


class DisplayNotSet(Exception):
    """Raised when a virtual display is required but not configured.

    Deliberately NOT a ``CFError`` subclass — display misconfiguration is
    an infrastructure / setup issue, not a Cloudflare challenge failure.
    Callers who want a single ``except`` should catch ``(CFError, DisplayNotSet)``.
    """

    def __init__(self, msg: str = "", **context: Any) -> None:
        super().__init__(msg)
        self.context: dict[str, Any] = context
