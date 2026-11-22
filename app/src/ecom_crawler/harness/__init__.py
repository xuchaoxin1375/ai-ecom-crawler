"""Build-time harness adapter boundary.

The execution runtime stays deterministic and harness-free.  This package only
contains the build-side adapter used by a future BuildService: workspace
layout, an OpenCode HTTP/SSE client, event normalization and the
``HarnessAdapter`` interface from ADR 0005/0006.
"""

from .adapter import BuildSession, HarnessAdapter, OpenCodeHttpAdapter
from .dependencies import DependencyPolicy, DependencyRequest
from .dependency_bridge import (
    DependencyBridge,
    install_dependency_tool,
)
from .events import normalize_event
from .models import BuildTask, HarnessEvent
from .opencode import OpenCodeClient, OpenCodeServer
from .pause_gate import install_pause_gate
from .service import BuildService
from .workspace import BuildWorkspace

__all__ = [
    "BuildService",
    "BuildSession",
    "BuildTask",
    "BuildWorkspace",
    "DependencyBridge",
    "DependencyPolicy",
    "DependencyRequest",
    "HarnessAdapter",
    "HarnessEvent",
    "OpenCodeClient",
    "OpenCodeHttpAdapter",
    "OpenCodeServer",
    "install_dependency_tool",
    "install_pause_gate",
    "normalize_event",
]
