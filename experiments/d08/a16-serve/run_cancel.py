from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8769"
EVIDENCE_ROOT = Path(
    os.environ.get("ECOM_EVIDENCE_ROOT", r"C:\repos\ai-ecom-crawler-evidence")
)
ROOT = EVIDENCE_ROOT / "experiments" / "d08" / "a16-serve"
ROOT.mkdir(parents=True, exist_ok=True)


def request(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


rules = request("GET", "/api/rules")
rule = next(item for item in rules["items"] if item["valid"] and "product" in item["task_types"])
created = request(
    "POST",
    "/api/tasks",
    {
        "request_id": f"a16-cancel-{int(time.time())}",
        "rule_id": rule["rule_id"],
        "rule_version": rule["rule_version"],
        "task_type": "product",
        "limits": {"max_products": 6, "max_urls": 20, "max_seconds": 180},
    },
)
task_id = created["task"]["task_id"]
request("POST", f"/api/tasks/{task_id}/start")

timeline = []
cancelled = False
started = time.monotonic()
final = None
while time.monotonic() - started < 120:
    task = request("GET", f"/api/tasks/{task_id}")
    timeline.append(
        {
            "t": round(time.monotonic() - started, 2),
            "state": task["state"],
            "counts": task["counts"],
        }
    )
    state = task["state"]
    if state == "RUNNING" and not cancelled and (
        task["counts"].get("valid_products", 0) >= 1
        or time.monotonic() - started > 3
    ):
        request("POST", f"/api/tasks/{task_id}/cancel")
        cancelled = True
    if state in {"CANCELLED", "FINISHED"}:
        final = task
        break
    time.sleep(0.25)

if final is None:
    final = request("GET", f"/api/tasks/{task_id}")
evidence = {"task_id": task_id, "timeline": timeline, "final": final}
(ROOT / "cancel-evidence.json").write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    json.dumps(
        {
            "task_id": task_id,
            "state": final["state"],
            "outcome": final["outcome"],
            "stop_reason": final["stop_reason"],
            "counts": final["counts"],
            "cancelled": cancelled,
        },
        ensure_ascii=False,
        indent=2,
    )
)
