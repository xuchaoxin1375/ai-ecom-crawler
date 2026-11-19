"""Command-line entry point for the javaestate.com Crawlee plan."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow both `python run.py` and `python -m crawlee_javaestate.runner` from the
# package directory.  The manifest points at this file.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from crawlee_javaestate.runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
