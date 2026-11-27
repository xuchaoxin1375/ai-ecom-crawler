from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ecom_crawler.runtime.system_metrics import SystemMetricsSampler

GB = 1024**3


class FakeClock:
    def __init__(self, *values: float) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


class FakePsutil:
    def __init__(self, fail_memory_after: int | None = None) -> None:
        self.cpu_calls = 0
        self.memory_calls = 0
        self.fail_memory_after = fail_memory_after

    def cpu_times(self) -> SimpleNamespace:
        self.cpu_calls += 1
        # Each pair adds 200 total ticks and 160 idle ticks: 20% busy.
        if self.cpu_calls == 1:
            return self._times(user=20, system=20, idle=160)
        if self.cpu_calls == 2:
            return self._times(user=40, system=40, idle=320)
        return self._times(user=60, system=60, idle=480)

    @staticmethod
    def _times(*, user: float, system: float, idle: float) -> SimpleNamespace:
        return SimpleNamespace(
            user=user,
            nice=0.0,
            system=system,
            idle=idle,
            iowait=0.0,
            irq=0.0,
            softirq=0.0,
            steal=0.0,
        )

    def cpu_count(self, logical: bool = True) -> int:
        return 8 if logical else 4

    def virtual_memory(self) -> SimpleNamespace:
        self.memory_calls += 1
        if (
            self.fail_memory_after is not None
            and self.memory_calls > self.fail_memory_after
        ):
            raise RuntimeError("memory sampling failed")
        return SimpleNamespace(total=16 * GB, available=6 * GB)

    def Process(self) -> SimpleNamespace:
        return SimpleNamespace(
            memory_info=lambda: SimpleNamespace(rss=128 * 1024 * 1024)
        )


class SystemMetricsSamplerTests(unittest.TestCase):
    def test_cpu_delta_memory_and_process_rss(self) -> None:
        sampler = SystemMetricsSampler(
            psutil_module=FakePsutil(),
            clock=FakeClock(0.0, 1.0),
        )

        snapshot = sampler.snapshot()

        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["cpu_percent"], 20.0)
        self.assertEqual(snapshot["cpu_count"], 8)
        self.assertEqual(snapshot["cpu_window_ms"], 1000)
        self.assertEqual(snapshot["memory_total_bytes"], 16 * GB)
        self.assertEqual(snapshot["memory_used_bytes"], 10 * GB)
        self.assertEqual(snapshot["memory_percent"], 62.5)
        self.assertEqual(snapshot["process_rss_bytes"], 128 * 1024 * 1024)
        self.assertIsNotNone(snapshot["sampled_at"])
        self.assertTrue(snapshot["sampled_at"].endswith("Z"))

    def test_short_window_does_not_fake_a_cpu_reading(self) -> None:
        sampler = SystemMetricsSampler(
            psutil_module=FakePsutil(),
            clock=FakeClock(0.0, 0.01),
        )

        snapshot = sampler.snapshot()

        self.assertTrue(snapshot["available"])
        self.assertIsNone(snapshot["cpu_percent"])
        self.assertIsNone(snapshot["cpu_window_ms"])

    def test_second_snapshot_uses_the_first_as_baseline(self) -> None:
        sampler = SystemMetricsSampler(
            psutil_module=FakePsutil(),
            clock=FakeClock(0.0, 1.0, 2.0),
        )

        first = sampler.snapshot()
        second = sampler.snapshot()

        self.assertEqual(first["cpu_percent"], 20.0)
        self.assertEqual(second["cpu_percent"], 20.0)
        self.assertEqual(second["cpu_window_ms"], 1000)

    def test_missing_psutil_returns_an_unavailable_snapshot(self) -> None:
        with patch("ecom_crawler.runtime.system_metrics.psutil", None):
            sampler = SystemMetricsSampler()
            snapshot = sampler.snapshot()

        self.assertFalse(snapshot["available"])
        self.assertIsNone(snapshot["cpu_percent"])
        self.assertIsNone(snapshot["memory_total_bytes"])

    def test_memory_failure_does_not_break_the_snapshot(self) -> None:
        sampler = SystemMetricsSampler(
            psutil_module=FakePsutil(fail_memory_after=1),
            clock=FakeClock(0.0, 1.0, 2.0),
        )
        sampler.snapshot()

        snapshot = sampler.snapshot()

        self.assertFalse(snapshot["available"])
        self.assertIsNone(snapshot["memory_total_bytes"])


if __name__ == "__main__":
    unittest.main()
