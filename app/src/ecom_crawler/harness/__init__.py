"""Build-time harness adapter boundary.

The execution runtime stays deterministic and harness-free.  This package only
contains the build-side adapter used by a future BuildService: workspace
layout, an OpenCode HTTP/SSE client, event normalization and the
``HarnessAdapter`` interface from ADR 0005/0006.
"""

from .adapter import BuildSession, HarnessAdapter, OpenCodeHttpAdapter
from .events import normalize_event
from .models import BuildTask, HarnessEvent
from .opencode import OpenCodeClient, OpenCodeServer
from .workspace import BuildWorkspace

__all__ = [
    "BuildSession",
    "BuildTask",
    "BuildWorkspace",
    "HarnessAdapter",
    "HarnessEvent",
    "OpenCodeClient",
    "OpenCodeHttpAdapter",
    "OpenCodeServer",
    "normalize_event",
]
