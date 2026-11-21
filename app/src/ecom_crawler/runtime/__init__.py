"""Ported R06 task runtime: ledger, discovery/product tasks and worker.

D04 v0 extracted this from ``experiments/r06`` to give the app a real
single-process execution entry.  It is not yet the final production runtime:
browser resources, cross-process leases and the app-native state model remain
follow-up work.
"""

__version__ = "0.1.0"
