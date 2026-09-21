"""Purpose: Allow `python -m jev_screen ...` as an alias of the `jev-screen` console script."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
