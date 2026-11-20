#!/usr/bin/env python3
"""R06 task runtime CLI entrypoint."""

from __future__ import annotations

import sys

from runtime.cli import main

if __name__ == "__main__":
    sys.exit(main())
