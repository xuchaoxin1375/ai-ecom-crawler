from __future__ import annotations

import json
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import jsonschema

from ecom_crawler.execution import run_task
from ecom_crawler.pipeline import export_candidates
from ecom_crawler.runtime.models import FetchResult, WorkItem
from ecom_crawler.runtime.runner import TaskRunner
from tests.support import base_task, serve_http_fixture
from tests.test_execution import RULE_TEMPLATE, product_html


def localized_product_html(
    base: str, index: int, lang: str, extra_head: str = ""
) -> str:
    html = product_html(base, index)
    html = html.replace("<html>", f'<html lang="{lang}">', 1)
    return html.replace("</head>", f"{extra_head}</head>", 1)


def fixture_server() -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def send_body(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            base = f"http://127.0.0.1:{self.server.server_port}"  # type: ignore[attr-defined]
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/":
                self.send_body(
                    200,
                    (
                        b'<html lang="en"><body>'
                        b'<a class="product" href="/p1.html?lang=fr">P1</a>'
                        b"</body></html>"
                    ),
                )
                return
            if parsed.path == "/p1.html":
                lang = (query.get("lang") or ["en"])[0]
                extra = ""
                if lang != "en":
                    extra = (
                        f'<link rel="alternate" hreflang="en-GB" '
                        f'href="{base}/p1.html?lang=en">'
                    )
                self.send_body(
                    200,
                    localized_product_html(base, 1, lang, extra).encode("utf-8"),
                )
                return
            if parsed.path == "/p403.html":
                self.send_body(403, b'<html lang="en"><body>Forbidden</body></html>')
                return
            if parsed.path == "/p401.html":
                self.send_body(401, b'<html lang="en"><body>Unauthorized</body></html>')
                return
            self.send_body(404, b"<html><body>Not found</body></html>")

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class StopEvidenceTests(unittest.TestCase):
    def run_seed(
        self, base: str, seed: str, *, locale: str = "en-GB"
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rule = root / "rule.yaml"
            text = RULE_TEMPLATE.replace("__BASE__", base)
            text = text.replace('locale: "en-GB"', f'locale: "{locale}"')
            rule.write_text(text, encoding="utf-8")
            result, _ = run_task(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="stop-evidence",
                task_type="product",
                max_products=1,
                max_seconds=10,
                max_attempts=1,
                per_domain_rps=50,
                seed_urls=[seed],
                discover=False,
            )
            return result

    def test_http_403_records_access_code_and_evidence(self) -> None:
        server, base = fixture_server()
        with serve_http_fixture(server):
            result = self.run_seed(base, f"{base}/p403.html")
        self.assertEqual(result["stop_reason"], "ACCESS_DENIED")
        self.assertEqual(result["outcome"], "FAILED")
        self.assertEqual(result["stop_detail_code"], "http_403")
        evidence = result["stop_evidence"]
        self.assertEqual(evidence["code"], "http_403")
        self.assertEqual(evidence["status"], 403)
        self.assertEqual(evidence["url"], f"{base}/p403.html")
        self.assertTrue(evidence["abandoned"])
        self.assertEqual(result["failure_classes"]["blocked"], 1)

    def test_http_401_records_http_401(self) -> None:
        server, base = fixture_server()
        with serve_http_fixture(server):
            result = self.run_seed(base, f"{base}/p401.html")
        self.assertEqual(result["stop_reason"], "ACCESS_DENIED")
        self.assertEqual(result["stop_detail_code"], "http_401")
        self.assertEqual(result["stop_evidence"]["status"], 401)

    def test_language_mismatch_stops_with_suggested_alternate(self) -> None:
        server, base = fixture_server()
        with serve_http_fixture(server):
            result = self.run_seed(base, f"{base}/p1.html?lang=fr")
        self.assertEqual(result["stop_reason"], "LANGUAGE_MISMATCH")
        self.assertEqual(result["stop_detail_code"], "language_mismatch")
        check = result["language_check"]
        self.assertEqual(check["status"], "mismatch")
        self.assertEqual(check["expected_primary"], "en")
        self.assertEqual(check["actual_primary"], "fr")
        self.assertEqual(check["source"], "html_lang")
        self.assertEqual(check["suggested_url"], f"{base}/p1.html?lang=en")
        self.assertTrue(check["multilingual"])
        self.assertEqual(result["stop_evidence"]["kind"], "language")

    def test_matching_language_does_not_stop(self) -> None:
        server, base = fixture_server()
        with serve_http_fixture(server):
            result = self.run_seed(base, f"{base}/p1.html?lang=en")
        self.assertEqual(result["stop_reason"], "NATURAL_END")
        self.assertEqual(result["language_check"]["status"], "matched")
        self.assertEqual(result["counts"]["valid_products"], 1)

    def test_product_page_language_is_checked_after_matching_entry(self) -> None:
        server, base = fixture_server()
        with serve_http_fixture(server), tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rule = root / "rule.yaml"
            rule.write_text(
                RULE_TEMPLATE.replace("__BASE__", base), encoding="utf-8"
            )
            result, _ = run_task(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="language-product",
                task_type="product",
                max_products=1,
                max_seconds=10,
                max_attempts=1,
                per_domain_rps=50,
            )
        self.assertEqual(result["stop_reason"], "LANGUAGE_MISMATCH")
        self.assertEqual(result["language_check"]["status"], "mismatch")
        self.assertEqual(result["language_check"]["actual_primary"], "fr")

    def test_challenge_evidence_uses_browser_signal(self) -> None:
        runner = TaskRunner.__new__(TaskRunner)
        runner.fetcher = SimpleNamespace(
            describe=lambda: {
                "engines_used": ["browser"],
                "rate_limit_events": 2,
                "last_retry_after": 60,
            }
        )
        item = WorkItem(
            task_id="task",
            item_id="item",
            item_type="product",
            url="https://example.test/p1.html",
            normalized_url="https://example.test/p1.html",
            attempts=1,
        )
        result = FetchResult(
            status=200,
            url=item.url,
            meta={"engine": "browser", "challenge_suspected": True},
        )
        evidence = runner._access_evidence(item, result, "challenge_unresolved")
        self.assertEqual(evidence["kind"], "challenge")
        self.assertEqual(evidence["engine"], "browser")
        self.assertTrue(evidence["challenge_suspected"])
        self.assertEqual(evidence["rate_limit_events"], 2)
        self.assertEqual(evidence["retry_after"], 60)

    def test_task_result_schema_accepts_language_mismatch(self) -> None:
        result = export_candidates(
            base_task(
                stop_reason="LANGUAGE_MISMATCH",
                stop_detail_code="language_mismatch",
                language_check={
                    "status": "mismatch",
                    "expected": "en-GB",
                    "expected_primary": "en",
                    "actual": "fr",
                    "actual_primary": "fr",
                    "source": "html_lang",
                    "url": "https://example.test/fr/page",
                    "multilingual": False,
                    "alternates": [],
                    "suggested_url": None,
                },
            ),
            [],
        )
        schema = jsonschema.Draft202012Validator(
            json.loads(
                (
                    Path(__file__).resolve().parents[1]
                    / "schemas"
                    / "task-result.schema.json"
                ).read_text(encoding="utf-8")
            )
        )
        errors = list(schema.iter_errors(result.task_result))
        self.assertEqual(errors, [], [error.message for error in errors])


if __name__ == "__main__":
    unittest.main()
