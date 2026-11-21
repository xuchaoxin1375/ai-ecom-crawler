"""Cross-process lease smoke test for app/ (D07).

Starts a local fixture site, submits two tasks, then runs two independent
worker processes against the same SQLite ledger.  Each worker must claim a
different task; output must contain one product per task and no duplicates.

Run with the app environment:

    python -m uv run --project app python experiments/d07/lease/multiprocess_demo.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RULE = """\
schema_version: "1.1"
rule_id: "lease-demo"
rule_version: "1.0.0"
kind: declarative
status: candidate

site:
  name: "Lease Demo"
  entry_urls: ["__BASE__/"]
  allowed_origins: ["__BASE__"]
  allowed_path_prefixes: ["/"]
  market: "GB"
  locale: "en-GB"
  currency: "GBP"

scope:
  include: ['^/p[0-9]+\\.html$']
  exclude: []
  max_products: 5
  max_seconds: 30

capabilities:
  discovery: true
  product: true

discovery:
  strategies: ["entry_links"]
  entry_url: "__BASE__/"
  link_selector: "a.product"
  product_url_patterns: ['^/p[0-9]+\\.html$']
  url_identity: "canonical"

fetch:
  default_engine: "static"
  concurrency: 1
  delay_ms: 1000
  retry: {max_attempts: 1, backoff_ms: 10}
  timeout_ms: 5000
  browser: false
  login: false
  challenge_handling: "none"

extract:
  fields:
    name:
      required: true
      fallbacks:
        - {type: css_text, selector: "h1", label: "h1"}
    price.amount:
      required: true
      fallbacks:
        - {type: css_attr, selector: 'meta[property="product:price:amount"]', attr: "content", label: "price"}
    price.currency:
      required: true
      fallbacks:
        - {type: css_attr, selector: 'meta[property="product:price:currency"]', attr: "content", label: "currency"}
    primary_image_url:
      required: true
      fallbacks:
        - {type: css_attr, selector: 'meta[property="og:image"]', attr: "content", label: "image", absolute: true}
    description_html:
      required: false
      fallbacks:
        - {type: css_html, selector: "div.desc", label: "description", description_status: "complete"}
    source_url:
      required: true
      fallbacks:
        - {type: canonical, label: "canonical"}

normalize:
  price:
    tax_basis: "unspecified"
    choose: "smaller_public_pair"
    positive_only: true
  description:
    mode: "clean_html"
    statuses: ["complete", "partial", "not_provided", "failed"]
  options:
    exclude_quantity: true
    strip_price_delta: true

validate:
  required_fields:
    - "name"
    - "price.amount"
    - "price.currency"
    - "primary_image_url"
    - "source_url"
  assertions:
    - {field: "price.amount", op: ">", value: 0}
  partial_description: "allowed_with_flag"

output:
  url_list:
    enabled: true
    columns: ["url", "source", "status", "title"]
    format: "csv"
  product_csv:
    enabled: true
    columns: 9
    format: "csv"
  task_result: true

task_defaults:
  max_urls: 5
  max_products: 5
  max_seconds: 30
  concurrency:
    navigation: 1
    product: 1

compatibility:
  os: ["windows", "linux"]
  runtime: "python>=3.11"
  dependencies: []
  browser: "none"

evidence:
  sample_urls: ["__BASE__/"]
  expected: []
  verified_at: null
  limitations: ["Local lease demo only."]

notes: "D07 cross-process lease demo."
"""

ENTRY = """\
<html><body>
<a class="product" href="/p1.html">One</a>
<a class="product" href="/p2.html">Two</a>
</body></html>
"""

PRODUCT = """\
<html><head>
<title>Product {number}</title>
<meta property="og:image" content="{base}/img/{number}.jpg">
<meta property="product:price:amount" content="12.00">
<meta property="product:price:currency" content="GBP">
<link rel="canonical" href="{base}/p{number}.html">
</head><body>
<h1 itemprop="name">Product {number}</h1>
<div class="desc"><p>Body {number}.</p></div>
</body></html>
"""

CHILD = """\
import sys
from pathlib import Path
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.runtime.worker import Worker

db, out_root = sys.argv[1], sys.argv[2]
worker = Worker(
    TaskStore(db),
    out_root=out_root,
    max_tasks=1,
    per_domain_rps=50,
    lease_ttl_seconds=2.0,
    heartbeat_interval=0.3,
)
started = worker.run_once(poll_interval=0.05)
print(f"worker={worker.owner} started={started}")
"""


class Handler(BaseHTTPRequestHandler):
    base = ""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path in {"/", ""}:
            body = ENTRY
        elif self.path.startswith("/p") and self.path.endswith(".html"):
            number = self.path.strip("/").removeprefix("p").removesuffix(".html")
            if number.isdigit():
                body = PRODUCT.format(number=number, base=self.base)
            else:
                self.send_error(404)
                return
        else:
            self.send_error(404)
            return
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def run_workers(db: Path, out_root: Path) -> list[str]:
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", CHILD, str(db), str(out_root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        for _ in range(2)
    ]
    outputs: list[str] = []
    for process in processes:
        stdout, _ = process.communicate(timeout=90)
        outputs.append(stdout.strip())
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep the task ledger and output")
    args = parser.parse_args()

    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Handler.base = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    db = root / "tasks.db"
    out_root = root / "tasks"
    rule_path = root / "rule.yaml"
    rule_path.write_text(RULE.replace("__BASE__", Handler.base), encoding="utf-8")

    try:
        for index in (1, 2):
            submitted = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ecom_crawler",
                    "submit",
                    "--rule",
                    str(rule_path),
                    "--db",
                    str(db),
                    "--task-id",
                    f"lease-demo-{index}",
                    "--max-products",
                    "2",
                    "--max-seconds",
                    "30",
                    "--max-attempts",
                    "1",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if submitted.returncode != 0:
                print(submitted.stdout)
                print(submitted.stderr, file=sys.stderr)
                return submitted.returncode
        outputs = run_workers(db, out_root)
        from ecom_crawler.runtime.store import TaskStore

        store = TaskStore(db)
        tasks = {task.task_id: task for task in store.list_tasks()}
        report = {
            "base": Handler.base,
            "workers": outputs,
            "tasks": {
                task_id: {
                    "state": task.state,
                    "outcome": task.outcome,
                    "lease_token": task.lease_token,
                    "lease_owner": task.lease_owner,
                    "counts": store.item_counts(task_id, "product"),
                }
                for task_id, task in sorted(tasks.items())
            },
            "products": {
                task_id: len(
                    (out_root / task_id / "products.jsonl").read_text(encoding="utf-8").splitlines()
                )
                for task_id in sorted(tasks)
                if (out_root / task_id / "products.jsonl").is_file()
            },
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.keep:
            print(f"kept: {root}")
            temporary = None
        return 0
    finally:
        server.shutdown()
        server.server_close()
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
