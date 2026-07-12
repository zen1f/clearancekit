"""``python -m clearancekit`` entry point."""

from __future__ import annotations

import sys

from clearancekit.cli import main

if __name__ == "__main__":
    sys.exit(main())
