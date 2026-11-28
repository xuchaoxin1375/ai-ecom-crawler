"""Process-level recovery drills for the crawler task ledger.

Cases:
  power   hard-kill the serving process mid-run, restart, verify accepted
          products, counts, products.jsonl and products.csv stay consistent.
  disk    hard-kill mid-run, delete/truncate the product log, restart, verify
          the export is rebuilt from durable accepted records.
  missing hard-kill mid-run, remove one durable product record and the product
          log, restart, verify a clear ENVIRONMENT_ERROR and partial snapshot.

The fixture site runs in this process and survives the server kill. Evidence is
written under the evidence root passed with --root.

Run from the repository root:

    python -m uv run --project app --extra dev --frozen --no-sync \
        python app/tests/recovery_drill.py all --root <evidence-dir>

This is an opt-in drill, not part of the default unit-test discovery. It starts
and kills a real ``serve`` process and uses a temporary ledger and loopback
fixture.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PRODUCT_COUNT = 12

RULE = """\
schema_version: "1.1"
rule_id: "drill-recovery"
rule_version: "2026.11.28-1"
kind: declarative
status: candidate

site:
  name: "Drill"
  entry_urls: ["__BASE__/"]
  allowed_origins: ["__BASE__"]
  allowed_path_prefixes: ["/"]
  market: "GB"
  locale: "en-GB"
  currency: "GBP"

scope:
  include: ['^/p[0-9]+\\.html$']
  exclude: []
  max_products: 12
  max_seconds: 300

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
  retry: {max_attempts: 1, backoff_ms: 100}
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
  product_csv:
    enabled: true
"""


def product_html(base: str, index: int) -> str:
    return f"""\
<html><head>
<link rel="canonical" href="{base}/p{index}.html">
<meta property="product:price:amount" content="{index}.50">
<meta property="product:price:currency" content="GBP">
<meta property="og:image" content="{base}/img/{index}.jpg">
</head><body><h1>Drill Product {index}</h1><div class="desc">Drill description {index}</div>
</body></html>"""


class Gate:
    def __init__(self, hold_index: int) -> None:
        self.hold_index = hold_index
        self.count = 0
        self.consumed = False
        self.active = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()

    def hold(self) -> None:
        with self.lock:
            self.count += 1
            should_hold = self.count == self.hold_index and not self.consumed
            if should_hold:
                self.consumed = True
                self.active.set()
        if should_hold:
            self.release.wait(timeout=30)


def start_fixture(delay: float = 0.05, hold_index: int = 4) -> tuple[ThreadingHTTPServer, str, Gate]:
    gate = Gate(hold_index)

    class QuietServer(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address) -> None:  # type: ignore[no-untyped-def]
            if isinstance(sys.exc_info()[1], ConnectionResetError):
                return
            super().handle_error(request, client_address)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            base = f"http://127.0.0.1:{self.server.server_port}"  # type: ignore[attr-defined]
            path = self.path.split("?", 1)[0]
            if path == "/robots.txt":
                self.send_error(404)
                return
            if path == "/":
                links = "".join(
                    f'<a class="product" href="/p{i}.html">Product {i}</a>'
                    for i in range(1, PRODUCT_COUNT + 1)
                )
                body = f"<html><body>{links}</body></html>".encode()
            elif path.startswith("/p") and path.endswith(".html"):
                try:
                    index = int(path[2:-5])
                except ValueError:
                    self.send_error(404)
                    return
                gate.hold()
                time.sleep(delay)
                body = product_html(base, index).encode()
            elif path.startswith("/img/"):
                body = bytes.fromhex(
                    "47494638396101000100800000000000ffffff21f90401000000002c"
                    "00000000010001000002024401003b"
                )
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = QuietServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", gate


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def child_env(scratch: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().endswith("_PROXY")}
    env.update(
        TMP=str(scratch),
        TEMP=str(scratch),
        TMPDIR=str(scratch),
        NO_PROXY="127.0.0.1,localhost",
        PYTHONUNBUFFERED="1",
    )
    return env


class Server:
    def __init__(
        self,
        root: Path,
        port: int,
        db: Path,
        out: Path,
        rules: Path,
        log: Path,
        *,
        no_worker: bool = False,
    ) -> None:
        self.root = root
        self.port = port
        self.db = db
        self.out = out
        self.rules = rules
        self.log = log
        self.no_worker = no_worker
        self.proc: subprocess.Popen[bytes] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self.log.parent.mkdir(parents=True, exist_ok=True)
        handle = self.log.open("ab")
        scratch = self.root / "tmp"
        scratch.mkdir(exist_ok=True)
        cmd = [
            sys.executable,
            "-m",
            "ecom_crawler.cli",
            "serve",
            "--db", str(self.db),
            "--out-root", str(self.out),
            "--rules-dir", str(self.rules),
            "--port", str(self.port),
            "--dev-no-auth",
            "--lease-ttl", "3",
            "--heartbeat-interval", "0.5",
            "--max-tasks", "1",
            "--per-domain-rps", "50",
        ]
        if self.no_worker:
            cmd.append("--no-worker")
        self.proc = subprocess.Popen(
            cmd,
            env=child_env(scratch),
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited early: {self.log.read_text(errors='replace')[-4000:]}")
            healthy = False
            try:
                with urlopen(f"{self.url}/api/health", timeout=1) as response:
                    healthy = response.status == 200
            except (OSError, URLError):
                healthy = False
            if healthy:
                return
            time.sleep(0.15)
        raise RuntimeError("server did not become healthy")

    def kill(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
            capture_output=True,
            check=False,
        )
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.kill()


def open_store(db: Path):
    from ecom_crawler.runtime.store import TaskStore

    return TaskStore(db)


def get_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read())


def wait_recovery_state(
    server: Server, task_id: str, expected: str, timeout: float
) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        last = get_json(f"{server.url}/api/tasks/{task_id}")
        if last.get("recovery_state") == expected:
            return last
        time.sleep(0.1)
    raise RuntimeError(f"recovery_state for {task_id} is not {expected}: {last}")


def wait_state(db: Path, task_id: str, state: str, timeout: float) -> None:
    store = open_store(db)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = store.get_task(task_id)
        if task is not None and task.state == state:
            return
        time.sleep(0.2)
    task = store.get_task(task_id)
    raise RuntimeError(f"task {task_id} did not reach {state}: {task.state if task else None}")


def snapshot(db: Path, task_id: str) -> dict:
    store = open_store(db)
    task = store.get_task(task_id)
    assert task is not None
    counts = store.item_counts(task_id, "product")
    return {
        "state": task.state,
        "outcome": task.outcome,
        "stop_reason": task.stop_reason,
        "counters": task.counters,
        "output": task.output,
        "counts": counts,
    }


def verify_finished(root: Path, db: Path, task_id: str, minimum_valid: int) -> dict:
    snapshot_after = snapshot(db, task_id)
    assert snapshot_after["state"] == "FINISHED", snapshot_after
    out = root / "out" / task_id
    result = json.loads((out / "task-result.json").read_text(encoding="utf-8"))
    with (out / "products.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    log_lines = [
        json.loads(line)
        for line in (out / "products.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    store = open_store(db)
    done_urls = {
        str(item.result.get("product_record", {}).get("source_url"))
        for item in store.items(task_id, "product")
        if item.state == "DONE"
    }
    assert result["counts"]["valid_products"] == len(rows) == len(log_lines) == len(done_urls)
    assert len(rows) >= minimum_valid
    assert len({row["source_url"] for row in rows}) == len(rows)
    assert {row["source_url"] for row in rows} == done_urls
    assert result["state"] == "FINISHED"
    assert result["outcome"] == "COMPLETED"
    assert result["stop_reason"] == "NATURAL_END"
    assert result["recovery"]["missing_product_records"] == 0
    assert result["recovery"]["takeover"]["reset"] >= 1
    assert snapshot_after["output"].get("recovered_at")
    return {"result": result, "rows": len(rows), "snapshot": snapshot_after}


def run_case(case: str, root: Path) -> dict:
    from ecom_crawler.execution import submit_task

    root.mkdir(parents=True, exist_ok=True)
    server, origin, gate = start_fixture()
    try:
        rules = root / "rules"
        rules.mkdir(exist_ok=True)
        rule_path = rules / "drill.yaml"
        rule_path.write_text(RULE.replace("__BASE__", origin), encoding="utf-8")
        task_id = f"drill-{case}-{int(time.time())}"
        submit_task(
            rule_path=rule_path,
            db_path=root / "tasks.db",
            task_id=task_id,
            max_products=PRODUCT_COUNT,
            max_seconds=300,
            max_attempts=2,
        )
        out = root / "out"
        port = free_port()
        server_proc = Server(root, port, root / "tasks.db", out, rules, root / f"serve-{case}.log")
        report: dict = {"case": case, "task_id": task_id, "origin": origin}
        server_proc.start()
        try:
            if not gate.active.wait(60):
                raise RuntimeError("fixture never held the in-flight product request")
            before = snapshot(root / "tasks.db", task_id)
            log_path = out / task_id / "products.jsonl"
            csv_path = out / task_id / "products.csv"
            report["before_kill"] = {
                "held_product": gate.hold_index,
                "snapshot": before,
                "product_lines": len(log_path.read_text(encoding="utf-8").splitlines()),
                "csv_exists": csv_path.is_file(),
            }
            assert before["state"] == "RUNNING"
            assert before["counts"].get("IN_FLIGHT", 0) >= 1
            accepted_before = {
                str(item.result.get("product_record", {}).get("source_url"))
                for item in open_store(root / "tasks.db").items(task_id, "product")
                if item.state == "DONE"
            }
            server_proc.kill()
            gate.release.set()
            post_kill = snapshot(root / "tasks.db", task_id)
            report["after_kill"] = post_kill
            assert post_kill["state"] == "RUNNING"
            assert post_kill["counts"].get("IN_FLIGHT", 0) >= 1
        finally:
            gate.release.set()
            server_proc.stop()

        waiting_server = Server(
            root,
            free_port(),
            root / "tasks.db",
            out,
            rules,
            root / f"serve-{case}-waiting.log",
            no_worker=True,
        )
        waiting_server.start()
        try:
            waiting_payload = wait_recovery_state(waiting_server, task_id, "WAITING_FOR_WORKER", 15)
            report["waiting_recovery"] = waiting_payload["recovery_state"]
        finally:
            waiting_server.stop()

        if case == "disk":
            log_path.unlink(missing_ok=True)
            if csv_path.is_file():
                csv_path.write_text("url,source,status,title\nstale,row\n", encoding="utf-8")
            report["disk_change"] = "products.jsonl deleted; products.csv replaced with stale content"
        elif case == "missing":
            log_path.unlink(missing_ok=True)
            if csv_path.is_file():
                csv_path.unlink()
            store = open_store(root / "tasks.db")
            done_items = [
                item for item in store.items(task_id, "product") if item.state == "DONE"
            ]
            target = done_items[0]
            result = dict(target.result)
            result.pop("product_record", None)
            with store._connect() as connection:  # drill-only direct mutation
                connection.execute(
                    "UPDATE task_items SET result_json = ? WHERE task_id = ? AND item_id = ?",
                    (json.dumps(result), task_id, target.item_id),
                )
            report["disk_change"] = f"removed durable product_record for {target.item_id}"

        server_proc.start()
        try:
            if case == "missing":
                wait_state(root / "tasks.db", task_id, "FINISHED", 60)
                after = snapshot(root / "tasks.db", task_id)
                out_dir = out / task_id
                result = json.loads((out_dir / "task-result.json").read_text(encoding="utf-8"))
                with (out_dir / "products.csv").open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                report["final"] = after
                report["task_result"] = result
                report["csv_rows"] = len(rows)
                assert after["state"] == "FINISHED"
                assert after["stop_reason"] == "ENVIRONMENT_ERROR"
                assert result["recovery"]["missing_product_records"] >= 1
                assert result["recovery"]["takeover"]["reset"] >= 1
                assert "缺少" in result["stop_detail"]
                assert len(rows) == after["counts"]["DONE"] - result["recovery"]["missing_product_records"]
                final_payload = get_json(f"{server_proc.url}/api/tasks/{task_id}")
                assert final_payload["recovery_state"] == "RESULT_INCOMPLETE", final_payload
                report["final_recovery"] = final_payload["recovery_state"]
            else:
                wait_state(root / "tasks.db", task_id, "FINISHED", 90)
                verified = verify_finished(root, root / "tasks.db", task_id, max(3, len(accepted_before)))
                report["final"] = verified["snapshot"]
                report["task_result"] = verified["result"]
                report["csv_rows"] = verified["rows"]
                final_payload = get_json(f"{server_proc.url}/api/tasks/{task_id}")
                assert final_payload["recovery_state"] == "RECOVERED", final_payload
                report["final_recovery"] = final_payload["recovery_state"]
        finally:
            server_proc.stop()
        return report
    finally:
        server.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=["power", "disk", "missing", "all"])
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    cases = ["power", "disk", "missing"] if args.case == "all" else [args.case]
    reports = []
    for case in cases:
        case_root = root / f"{case}-{time.strftime('%H%M%S')}"
        report = run_case(case, case_root)
        (case_root / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        reports.append({"case": case, "root": str(case_root)})
        print(json.dumps({"case": case, "root": str(case_root), "ok": True}, ensure_ascii=False))
    (root / "summary.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
