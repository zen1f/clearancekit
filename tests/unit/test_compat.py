"""Tests for clearancekit._compat.nodriver patch."""

from unittest.mock import MagicMock, patch

from clearancekit._compat.nodriver import _PATCHED_FLAG, apply


def test_apply_is_idempotent():
    """Calling apply() twice must not double-patch."""
    fake_cdp = MagicMock()
    fake_cookie_cls = MagicMock()
    fake_cookie_cls.from_json = lambda j: j  # original
    fake_cdp.network.Cookie = fake_cookie_cls

    with patch(
        "clearancekit._compat.nodriver._get_cookie_cls",
        return_value=fake_cookie_cls,
    ):
        # reset patched flag
        if hasattr(fake_cookie_cls, _PATCHED_FLAG):
            delattr(fake_cookie_cls, _PATCHED_FLAG)
        apply()
        first_fn = fake_cookie_cls.from_json
        apply()  # second call no-ops
        second_fn = fake_cookie_cls.from_json
        assert first_fn is second_fn
        assert getattr(fake_cookie_cls, _PATCHED_FLAG) is True


def test_apply_tolerates_null_same_site():
    """Patched from_json should accept JSON with sameSite=None."""
    fake_cookie_cls = MagicMock()
    received = {}

    def original_from_json(j):
        # simulate strict original that crashes when sameSite is explicitly None
        if "sameSite" in j and j["sameSite"] is None:
            raise ValueError("None sameSite not handled")
        received.update(j)
        return MagicMock()

    fake_cookie_cls.from_json = original_from_json

    with patch(
        "clearancekit._compat.nodriver._get_cookie_cls",
        return_value=fake_cookie_cls,
    ):
        if hasattr(fake_cookie_cls, _PATCHED_FLAG):
            delattr(fake_cookie_cls, _PATCHED_FLAG)
        apply()
        # Now patched from_json should tolerate null sameSite
        fake_cookie_cls.from_json({"name": "c", "value": "v", "sameSite": None})
        assert received["name"] == "c"
