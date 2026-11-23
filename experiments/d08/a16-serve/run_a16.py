from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import zipfile
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
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {payload}") from exc


rules = request("GET", "/api/rules")
rule = next(item for item in rules["items"] if item["valid"] and "product" in item["task_types"])
request_id = f"a16-{int(time.time())}"
created = request(
    "POST",
    "/api/tasks",
    {
        "request_id": request_id,
        "rule_id": rule["rule_id"],
        "rule_version": rule["rule_version"],
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
print("created", task_id, created["task"]["state"])
request("POST", f"/api/tasks/{task_id}/start")

timeline: list[dict] = []
paused = False
resumed = False
archive_tested = False
started = time.monotonic()
final = None
while time.monotonic() - started < 180:
    task = request("GET", f"/api/tasks/{task_id}")
    timeline.append(
        {
            "t": round(time.monotonic() - started, 2),
            "state": task["state"],
            "counts": task["counts"],
        }
    )
    state = task["state"]
    if state == "RUNNING" and not paused:
        elapsed = time.monotonic() - started
        if task["counts"].get("valid_products", 0) >= 1 or elapsed > 3:
            try:
                request("POST", f"/api/tasks/{task_id}/pause")
                paused = True
                print("pause requested at", round(elapsed, 2))
            except RuntimeError as exc:
                print("pause not accepted:", exc)
    if state == "PAUSED" and paused and not resumed:
        time.sleep(1)
        request("POST", f"/api/tasks/{task_id}/resume")
        resumed = True
        print("resumed")
    if state in {"FINISHED", "CANCELLED"}:
        final = task
        break
    time.sleep(0.25)

if final is None:
    final = request("GET", f"/api/tasks/{task_id}")
if final["state"] == "FINISHED" and not archive_tested:
    request("POST", f"/api/tasks/{task_id}/archive")
    default_list = request("GET", "/api/tasks")
    archived_list = request("GET", "/api/tasks?include_archived=true")
    request("POST", f"/api/tasks/{task_id}/restore")
    archive_tested = True
    archive_evidence = {
        "default_contains": any(
            item["task_id"] == task_id for item in default_list["items"]
        ),
        "archived_contains": any(
            item["task_id"] == task_id for item in archived_list["items"]
        ),
    }
else:
    archive_evidence = {}

items = request("GET", f"/api/tasks/{task_id}/items?kind=product&limit=200")
urls = request("GET", f"/api/tasks/{task_id}/items?kind=url&limit=200")
export_path = ROOT / "export.zip"
urllib.request.urlretrieve(f"{BASE}/api/tasks/{task_id}/export", export_path)
with zipfile.ZipFile(export_path) as archive:
    export_names = archive.namelist()

evidence = {
    "rule": rule,
    "request_id": request_id,
    "task_id": task_id,
    "timeline": timeline,
    "final": final,
    "archive": archive_evidence,
    "items": {"products": items["total"], "urls": urls["total"]},
    "export_files": export_names,
}
(ROOT / "evidence.json").write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps({
    "task_id": task_id,
    "final_state": final["state"],
    "outcome": final["outcome"],
    "stop_reason": final["stop_reason"],
    "counts": final["counts"],
    "paused": paused,
    "resumed": resumed,
    "archive": archive_evidence,
    "items": evidence["items"],
    "export_files": export_names,
}, ensure_ascii=False, indent=2))
