"""Stable identity for a running panel instance.

``code_fingerprint`` covers the Python package that the process imported at
startup; ``frontend_info`` covers the built v2 entry file; ``git_info`` is a
display-only view of the checkout.  The development script compares the live
health payload with the current checkout so an old process on the canonical
port is visible instead of silently serving stale code.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

_SUBPROCESS_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


@lru_cache(maxsize=8)
def code_fingerprint(package_root: str | Path) -> str:
    """Return a short digest of all Python sources under ``package_root``.

    The digest is computed once per process for startup identity.  Callers that
    need the current tree (for example the dev script) run in a fresh process,
    so the cache never hides an edit made after startup.
    """
    root = Path(package_root).resolve()
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts:
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def frontend_info(dist_dir: str | Path) -> dict[str, Any]:
    """Describe the built ``index.html`` without reading the whole bundle."""
    index = Path(dist_dir) / "index.html"
    if not index.is_file():
        return {"exists": False, "sha256": None, "built_at": None}
    stat = index.stat()
    built_at = (
        datetime.fromtimestamp(stat.st_mtime, UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    return {
        "exists": True,
        "sha256": hashlib.sha256(index.read_bytes()).hexdigest()[:16],
        "built_at": built_at,
    }


@lru_cache(maxsize=4)
def git_info(repo_root: str | Path) -> dict[str, Any]:
    """Return the current commit and dirty flag, or ``None`` values outside git."""
    root = Path(repo_root)
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
            creationflags=_SUBPROCESS_FLAGS,
        )
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            creationflags=_SUBPROCESS_FLAGS,
        )
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}
    commit_text = commit.stdout.strip() if commit.returncode == 0 else ""
    dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    return {"commit": commit_text or None, "dirty": dirty}
