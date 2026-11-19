#!/usr/bin/env python
"""Entrypoint for the javaestate.com Scrapling plan.

Usage:
  python run.py --out-dir . --label run-001
  python run.py --out-dir . --label fix-rerun --max-products 30
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from javaestate_scraper.runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
