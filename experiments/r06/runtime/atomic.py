"""Crash-tolerant output helpers for the R06 runtime prototype."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_DEFAULT_LOCK = threading.Lock()


def write_text(path: Path, text: str, *, lock: threading.Lock | None = None) -> None:
    """Write a whole file through a temporary file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with (lock or _DEFAULT_LOCK):
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)


def write_json(
    path: Path, payload: Any, *, lock: threading.Lock | None = None
) -> None:
    write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        lock=lock,
    )


def append_jsonl(
    path: Path,
    payload: dict[str, Any],
    *,
    lock: threading.Lock | None = None,
) -> None:
    """Append one complete line in a single write and fsync it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    with (lock or _DEFAULT_LOCK):
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
