"""Append-only request telemetry for one task run.

The runtime already writes item events to ``events.ndjson``.  Request-level
attempts have a different lifecycle and a much higher volume, so they live in a
separate ``requests.ndjson`` file.  The file is diagnostic evidence, not a
deliverable: it is capped, flushed per line and safe to truncate.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self, TextIO

logger = logging.getLogger(__name__)

DEFAULT_MAX_RECORDS = 200_000
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
_TRUNCATION_MARKER_RESERVE = 512


def utc_now_ms() -> str:
    """UTC timestamp with millisecond precision for request attempts."""

    return (
        datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class RequestRecorder:
    """Thread-safe NDJSON writer with line and byte limits.

    A line is flushed as soon as it is written (line buffering), so a live
    analysis request can see new attempts without waiting for a task to end.
    The recorder never raises into the fetch path: an unwritable telemetry file
    disables further records and leaves the crawl unaffected.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_records: int = DEFAULT_MAX_RECORDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self.path = Path(path)
        self.max_records = max(1, int(max_records))
        self.max_bytes = max(1024, int(max_bytes))
        self._lock = threading.Lock()
        self._handle: TextIO | None = None
        self._records = 0
        self._bytes = 0
        self._truncated = False
        self._truncation_reason: str | None = None
        self._open()

    def _open(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            last_line = ""
            if self.path.exists():
                self._bytes = self.path.stat().st_size
                if self._bytes:
                    with self.path.open(
                        "r", encoding="utf-8", errors="replace"
                    ) as existing:
                        for line in existing:
                            if line.strip():
                                self._records += 1
                                last_line = line
            self._handle = self.path.open(
                "a",
                encoding="utf-8",
                newline="",
                buffering=1,
            )
            try:
                marker = json.loads(last_line) if last_line else {}
            except json.JSONDecodeError:
                marker = {}
            if isinstance(marker, dict) and marker.get("event") == "truncated":
                self._truncated = True
                self._truncation_reason = "existing"
                return
        except OSError:
            logger.warning("request telemetry disabled: %s", self.path, exc_info=True)
            self._handle = None
            return
        if self._at_limit():
            self._truncated = True
            self._truncation_reason = "existing"
            self._write_truncation_marker_locked("existing")

    def record(self, payload: dict[str, Any]) -> None:
        """Append one request attempt.  Invalid or oversized payloads are ignored."""

        try:
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        except (TypeError, ValueError):
            return
        size = len(line.encode("utf-8"))
        with self._lock:
            handle = self._handle
            if handle is None or self._truncated:
                return
            if self._records + 1 > self.max_records:
                self._truncate_locked("records")
                return
            if self._bytes + size + _TRUNCATION_MARKER_RESERVE > self.max_bytes:
                self._truncate_locked("bytes")
                return
            try:
                handle.write(line)
            except OSError:
                logger.warning(
                    "request telemetry write failed; disabling: %s",
                    self.path,
                    exc_info=True,
                )
                self._handle = None
                return
            self._records += 1
            self._bytes += size

    def _at_limit(self) -> bool:
        return (
            self._records >= self.max_records
            or self._bytes + _TRUNCATION_MARKER_RESERVE >= self.max_bytes
        )

    def _truncate_locked(self, reason: str) -> None:
        if self._truncated:
            return
        self._truncated = True
        self._truncation_reason = reason
        self._write_truncation_marker_locked(reason)

    def _write_truncation_marker_locked(self, reason: str) -> None:
        handle = self._handle
        if handle is None:
            return
        marker = {
            "ts": utc_now_ms(),
            "event": "truncated",
            "reason": reason,
            "records": self._records,
        }
        try:
            handle.write(json.dumps(marker, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning(
                "request telemetry truncation marker failed: %s",
                self.path,
                exc_info=True,
            )
            self._handle = None

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "records": self._records,
                "bytes": self._bytes,
                "truncated": self._truncated,
                "reason": self._truncation_reason,
            }

    def close(self) -> None:
        with self._lock:
            handle, self._handle = self._handle, None
            if handle is None:
                return
            try:
                handle.close()
            except OSError:
                logger.debug("request telemetry close failed", exc_info=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
