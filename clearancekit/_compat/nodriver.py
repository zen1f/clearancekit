"""Lazy monkey-patches for nodriver upstream quirks.

Call ``apply()`` before using nodriver. Idempotent — repeated calls are
no-ops (guarded by a ``_clearancekit_patched`` attribute on the target class).

Currently patches:
  - ``cdp.network.Cookie.from_json``: tolerate ``sameSite=None`` (nodriver
    versions in 0.36.x raise on this; CF cookies sometimes have it).
"""

from __future__ import annotations

from typing import Any

_PATCHED_FLAG = "_clearancekit_patched"


def _get_cookie_cls() -> Any:
    """Indirect import for testability."""
    from nodriver.cdp.network import Cookie

    return Cookie


def apply() -> None:
    """Apply all compat patches. Safe to call repeatedly."""
    cookie_cls = _get_cookie_cls()
    if getattr(cookie_cls, _PATCHED_FLAG, False):
        return

    original = cookie_cls.from_json

    def patched_from_json(json_data: dict[str, Any]) -> Any:
        data = dict(json_data)
        if data.get("sameSite") is None:
            data.pop("sameSite", None)
        return original(data)

    cookie_cls.from_json = patched_from_json
    setattr(cookie_cls, _PATCHED_FLAG, True)
