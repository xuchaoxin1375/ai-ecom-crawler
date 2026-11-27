"""Lightweight CPU and memory sampling for the system status endpoint.

The sampler is intentionally request-driven: it does not start a background
thread and does not persist samples. CPU usage is the average since the
previous snapshot, which keeps the call cheap and avoids blocking a request
for a fixed interval. The first snapshot may not have a usable CPU value; the
API returns ``None`` instead of pretending the machine was idle.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

try:  # pragma: no cover - the fallback is covered by an explicit test
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class SystemMetricsSampler:
    """Return a best-effort CPU/memory snapshot without failing the request."""

    def __init__(
        self,
        psutil_module: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._psutil = psutil if psutil_module is None else psutil_module
        self._clock = clock
        self._lock = threading.Lock()
        self._last_cpu: tuple[float, float] | None = None
        self._last_at: float | None = None
        if self._psutil is not None:
            try:
                self._last_cpu = self._read_cpu_times()
                self._last_at = self._clock()
            except Exception:  # noqa: BLE001 - a platform probe must not break /api/system
                # A platform can expose psutil but still reject cpu_times();
                # treat it as unavailable rather than breaking /api/system.
                self._psutil = None

    def _read_cpu_times(self) -> tuple[float, float]:
        times = self._psutil.cpu_times()
        total = sum(
            float(getattr(times, field, 0.0))
            for field in (
                "user",
                "nice",
                "system",
                "idle",
                "iowait",
                "irq",
                "softirq",
                "steal",
            )
        )
        idle = float(getattr(times, "idle", 0.0)) + float(
            getattr(times, "iowait", 0.0)
        )
        return total, idle

    @staticmethod
    def unavailable() -> dict[str, Any]:
        return {
            "available": False,
            "cpu_percent": None,
            "cpu_count": None,
            "cpu_window_ms": None,
            "memory_used_bytes": None,
            "memory_total_bytes": None,
            "memory_percent": None,
            "process_rss_bytes": None,
            "sampled_at": None,
        }

    def snapshot(self) -> dict[str, Any]:
        if self._psutil is None:
            return self.unavailable()
        with self._lock:
            sampled_at = utc_now_iso()
            now = self._clock()
            try:
                total, idle = self._read_cpu_times()
                cpu_percent: float | None = None
                cpu_window_ms: int | None = None
                if self._last_cpu is not None and self._last_at is not None:
                    delta_total = total - self._last_cpu[0]
                    delta_idle = idle - self._last_cpu[1]
                    elapsed = now - self._last_at
                    if delta_total > 0 and elapsed >= 0.05:
                        cpu_percent = round(
                            max(
                                0.0,
                                min(100.0, (1.0 - delta_idle / delta_total) * 100.0),
                            ),
                            1,
                        )
                        cpu_window_ms = max(1, int(elapsed * 1000))
                self._last_cpu = (total, idle)
                self._last_at = now

                memory = self._psutil.virtual_memory()
                total_memory = int(memory.total)
                available_memory = int(memory.available)
                used_memory = max(0, total_memory - available_memory)
                memory_percent = round(
                    (used_memory / total_memory * 100.0) if total_memory else 0.0,
                    1,
                )
                process_rss_bytes: int | None
                try:
                    process_rss_bytes = int(self._psutil.Process().memory_info().rss)
                except Exception:  # noqa: BLE001 - process RSS is optional context
                    process_rss_bytes = None
                return {
                    "available": True,
                    "cpu_percent": cpu_percent,
                    "cpu_count": self._psutil.cpu_count(logical=True),
                    "cpu_window_ms": cpu_window_ms,
                    "memory_used_bytes": used_memory,
                    "memory_total_bytes": total_memory,
                    "memory_percent": memory_percent,
                    "process_rss_bytes": process_rss_bytes,
                    "sampled_at": sampled_at,
                }
            except Exception:  # noqa: BLE001 - monitoring fallback must stay total
                # Keep the previous baseline so a transient failure does not
                # turn into a permanent CPU=0 reading on the next request.
                return self.unavailable()
