#!/usr/bin/env python3
"""R06 declarative executor entrypoint."""

from __future__ import annotations

import sys

from executor.cli import main

if __name__ == "__main__":
    sys.exit(main())
