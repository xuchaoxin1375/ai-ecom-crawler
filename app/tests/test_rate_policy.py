import datetime as dt
import unittest
from email.utils import format_datetime

from ecom_crawler.rate_policy import (
    RatePolicyError,
    effective_policy,
    normalize_domain,
    validate_policy,
)
from ecom_crawler.runtime.fetcher import (
    DomainLimiter,
    ScraplingFetcher,
    retry_after_seconds,
)


class RatePolicyTests(unittest.TestCase):
    def test_normalize_domain_accepts_hosts_and_urls(self) -> None:
        self.assertEqual(normalize_domain("WWW.Example.FR."), "www.example.fr")
        self.assertEqual(
            normalize_domain("https://www.example.fr/products/1"),
            "www.example.fr",
        )

    def test_validate_policy_rejects_unknown_and_out_of_range(self) -> None:
        self.assertEqual(
            validate_policy(
                {
                    "per_domain_rps": 4,
                    "concurrency": 4,
                    "delay_ms": 250,
                    "max_attempts": 3,
                    "backoff_ms": 2000,
                }
            ),
            {
                "per_domain_rps": 4.0,
                "concurrency": 4,
                "delay_ms": 250,
                "max_attempts": 3,
                "backoff_ms": 2000,
            },
        )
        with self.assertRaises(RatePolicyError):
            validate_policy({"concurrency": 0})
        with self.assertRaises(RatePolicyError):
            validate_policy({"per_domain_rps": 11})
        with self.assertRaises(RatePolicyError):
            validate_policy({"rps": 2})

    def test_effective_policy_prefers_explicit_values(self) -> None:
        effective = effective_policy(
            {"per_domain_rps": 4, "concurrency": 3},
            default_rps=1.0,
            rule_fetch={"retry": {"max_attempts": 3, "backoff_ms": 1500}},
        )
        self.assertEqual(effective["per_domain_rps"], 4)
        self.assertEqual(effective["concurrency"], 3)
        self.assertEqual(effective["max_attempts"], 3)
        self.assertEqual(effective["backoff_ms"], 1500)
        self.assertEqual(effective["delay_ms"], 0)


class DomainLimiterTests(unittest.TestCase):
    def test_retry_after_accepts_seconds_and_http_date(self) -> None:
        self.assertEqual(retry_after_seconds({"Retry-After": "2"}), 2.0)
        future = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=10)
        parsed = retry_after_seconds(
            {"Retry-After": format_datetime(future, usegmt=True)}
        )
        assert parsed is not None
        self.assertGreaterEqual(parsed, 8.0)
        self.assertLessEqual(parsed, 12.0)
        self.assertIsNone(retry_after_seconds({}))

    def test_limiter_halves_and_recovers_after_429(self) -> None:
        limiter = DomainLimiter(1.0)
        limiter.configure("example.fr", 4.0)
        self.assertEqual(limiter.metrics()["current_rps"]["example.fr"], 4.0)
        limiter.penalize("https://example.fr/product", 2.0)
        metrics = limiter.metrics()
        self.assertEqual(metrics["current_rps"]["example.fr"], 2.0)
        self.assertEqual(metrics["rate_limit_events"], 1)
        self.assertEqual(metrics["last_retry_after"], 2.0)
        for _ in range(20):
            limiter.success("https://example.fr/product")
        self.assertEqual(limiter.metrics()["current_rps"]["example.fr"], 2.5)

    def test_static_fetcher_retries_429_and_records_it(self) -> None:
        class Response:
            def __init__(self, status: int, headers: dict[str, str]) -> None:
                self.status = status
                self.body = b"ok" if status == 200 else b"limited"
                self.url = "https://example.fr/product"
                self.headers = headers

        class Session:
            def __init__(self) -> None:
                self.calls = 0

            def get(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return Response(429, {"Retry-After": "0"})
                return Response(200, {"Content-Type": "text/html"})

        limiter = DomainLimiter(1.0)
        fetcher = ScraplingFetcher(
            Session(),
            limiter=limiter,
            max_attempts=2,
            backoff_ms=0,
        )
        result = fetcher.get("https://example.fr/product")
        self.assertEqual(result.status, 200)
        self.assertEqual(fetcher.requests, 2)
        self.assertEqual(fetcher.rate_limit_events, 1)
        self.assertEqual(limiter.metrics()["rate_limit_events"], 1)
        self.assertEqual(limiter.metrics()["current_rps"]["example.fr"], 0.5)
