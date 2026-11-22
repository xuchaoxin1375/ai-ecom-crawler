"""Run one real Familidoo task and serve it as a live D08 preview.

This is not a mock preview: it uses the managed rule package
``experiments/d03/familidoo``, creates a real product task through the local
API, waits for the worker, and keeps ``serve`` running so the page can be
checked against the real ledger and result.

Run from the repository root:

    app/.venv/Scripts/python.exe experiments/d08/ui-preview/run_real_preview.py --port 8775
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

RULES_DIR = Path("experiments/d03/familidoo").resolve()
RULE_ID = "familidoo-fr-d03"
RULE_VERSION = "2026.11.21-1"


def _request(url: str, *, method: str = "GET", body: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        headers["X-Requested-With"] = "XMLHttpRequest"
        parsed = urlsplit(url)
        headers["Origin"] = f"{parsed.scheme}://{parsed.netloc}"
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload) if payload else {}


def _wait_ready(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=2):
                return
        except Exception:  # noqa: BLE001 - readiness loop
            time.sleep(0.2)
    raise RuntimeError("serve did not become ready")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8775)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--max-seconds", type=float, default=180)
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="ecom-d08-real-preview-"))
    db = work / "tasks.db"
    out_root = work / "tasks"
    out_root.mkdir()
    url = f"http://{args.host}:{args.port}"
    print(f"workspace: {work}", flush=True)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ecom_crawler",
            "serve",
            "--db",
            str(db),
            "--out-root",
            str(out_root),
            "--rules-dir",
            str(RULES_DIR),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        cwd=Path.cwd(),
    )
    try:
        _wait_ready(url)
        created = _request(
            url + "/api/tasks",
            method="POST",
            body={
                "request_id": f"real-preview-{int(time.time())}",
                "rule_id": RULE_ID,
                "rule_version": RULE_VERSION,
                "task_type": "product",
                "limits": {
                    "max_products": 6,
                    "max_urls": 20,
                    "max_seconds": 180,
                    "max_attempts": 2,
                },
            },
        )
        task_id = created["task"]["task_id"]
        _request(f"{url}/api/tasks/{task_id}/start", method="POST")
        print(f"task: {task_id}", flush=True)
        deadline = time.monotonic() + args.max_seconds
        task = created["task"]
        while time.monotonic() < deadline:
            task = _request(f"{url}/api/tasks/{task_id}")
            print(
                f"state: {task['state']} valid={task['counts'].get('valid_products', 0)} "
                f"failed={task['counts'].get('failed_products', 0)}",
                flush=True,
            )
            if task["state"] in {"FINISHED", "CANCELLED"}:
                break
            time.sleep(1)
        print(
            json.dumps(
                {
                    "task_id": task_id,
                    "state": task.get("state"),
                    "outcome": task.get("outcome"),
                    "stop_reason": task.get("stop_reason"),
                    "counts": task.get("counts"),
                    "quality_exceptions": len(task.get("quality_exceptions") or []),
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )
        print(f"preview: {url}", flush=True)
        print("real ledger; Ctrl+C stops the preview", flush=True)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
