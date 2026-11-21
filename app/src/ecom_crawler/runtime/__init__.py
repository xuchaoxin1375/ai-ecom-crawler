"""Ported R06 task runtime: ledger, discovery/product tasks and worker.

D04 v0 extracted this from ``experiments/r06`` to give the app a real
execution entry.  The runtime uses SQLite task leases for cooperating worker
processes and a task-owned process/path resource registry.  The browser
adapter launches a task-owned Chromium over CDP and reuses one page; load-more
and scrolling actions remain follow-up work.
"""

__version__ = "0.1.0"
