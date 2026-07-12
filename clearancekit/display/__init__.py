"""X11 virtual display management."""

from clearancekit.display.backend import DisplayBackend
from clearancekit.display.xvfb import XvfbBackend, xvfb

__all__ = [
    "DisplayBackend",
    "XvfbBackend",
    "xvfb",
]
