#!/usr/bin/env python
"""Entrypoint for the skatepro.es Scrapling plan.

Usage:
  python -m uv run --project experiments/framework-compare/scrapling \
    python experiments/d01/skatepro/run.py \
    --out-dir experiments/d01/skatepro --label d01-run-001
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skatepro_scraper.runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
