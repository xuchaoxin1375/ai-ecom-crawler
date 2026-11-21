"""Ported R06 task runtime: ledger, discovery/product tasks and worker.

D04 v0 extracted this from ``experiments/r06`` to give the app a real
execution entry.  The runtime now uses SQLite task leases for cooperating
worker processes and has a task-owned process/path resource registry.  The
same-process browser adapter and per-task process isolation remain follow-up
work.
"""

__version__ = "0.1.0"
