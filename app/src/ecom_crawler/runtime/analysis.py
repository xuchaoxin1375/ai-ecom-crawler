"""Read-only aggregation for the single-run analysis tab.

The analysis is a projection of existing task artifacts plus the optional
``requests.ndjson`` written by the runtime.  It never mutates task state and
never reads the task database directly; the web layer passes the authoritative
counts and terminal result.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import Counter, OrderedDict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Task

MAX_POINTS = 720
DEFAULT_BUCKET_SECONDS = 60
LONG_RUN_BUCKET_SECONDS = 300
LONG_RUN_THRESHOLD_SECONDS = 3600
RECENT_BUCKETS = 5
FAILURE_PEAK_MIN = 4
FAILURE_REASON_LIMIT = 5

TERMINAL_STATES = {"CANCELLED", "FINISHED"}

FAILURE_REASON_LABELS = {
    "validation_error": "商品数据校验失败",
    "access_denied": "访问被拒绝",
    "challenge": "挑战页未解除",
    "challenge_unresolved": "挑战页未解除",
    "http_401": "需要登录或授权",
    "http_403": "访问被拒绝（403）",
    "http_404": "页面不存在",
    "http_410": "页面已移除",
    "http_429": "请求被限流",
    "transport_error": "网络或传输失败",
    "timeout": "请求超时",
    "adapter_error": "适配器失败",
    "public_json_parse_error": "公开 JSON 解析失败",
    "public_json_items_not_found": "公开 JSON 未找到商品",
    "sitemap_parse_error": "站点地图解析失败",
    "sitemap_gzip_error": "站点地图解压失败",
    "source_url_not_allowed": "来源网址不在允许范围",
    "task_cancelled": "任务取消",
    "unknown": "未知失败",
}

COVERAGE_LABELS = {
    "COMPLETE": "已覆盖",
    "KNOWN": "已覆盖",
    "PARTIAL": "部分覆盖",
    "UNKNOWN": "覆盖未知",
}

_CACHE_MAX = 16
_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def clear_analysis_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _bucket_start(value: datetime, seconds: int) -> datetime:
    timestamp = int(value.timestamp())
    return datetime.fromtimestamp(timestamp - timestamp % seconds, UTC)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _iter_jsonl(path: Path) -> Iterable[tuple[dict[str, Any] | None, bool]]:
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                yield None, False
                continue
            if not isinstance(payload, dict):
                yield None, False
                continue
            yield payload, True


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_bucket(run_seconds: float, requested: int | None) -> int:
    if requested and requested >= 60:
        return int(requested)
    return (
        LONG_RUN_BUCKET_SECONDS
        if run_seconds > LONG_RUN_THRESHOLD_SECONDS
        else DEFAULT_BUCKET_SECONDS
    )


def _failure_label(code: str) -> str:
    if code in FAILURE_REASON_LABELS:
        return FAILURE_REASON_LABELS[code]
    if code.startswith("item_error:"):
        return "工作项处理异常"
    return code.replace("_", " ")


def _coverage_payload(result: dict[str, Any]) -> dict[str, Any]:
    raw = result.get("coverage") or {}
    if not isinstance(raw, dict):
        return {"status": "UNKNOWN", "label": "覆盖未知"}
    status = str(raw.get("status") or "UNKNOWN").upper()
    denominator = _as_int(raw.get("denominator"))
    covered = _as_int(raw.get("covered"))
    label = COVERAGE_LABELS.get(status, status)
    if denominator > 0:
        label = f"声明来源内 {covered / denominator:.0%}"
    return {
        "status": status,
        "label": label,
        "denominator": denominator or None,
        "covered": covered or None,
        "denominator_source": raw.get("denominator_source"),
        "notes": raw.get("notes"),
    }


def _active_intervals(
    started: datetime,
    observed: datetime,
    run_events: list[tuple[datetime, str]],
) -> list[dict[str, str]]:
    intervals: list[tuple[datetime, datetime]] = []
    open_start: datetime | None = started
    for timestamp, event in run_events:
        if timestamp < started or timestamp > observed:
            continue
        if event == "task_started":
            if open_start is None:
                open_start = timestamp
            continue
        if event in {"task_paused", "task_finished", "task_error"} and (
            open_start is not None and timestamp >= open_start
        ):
            intervals.append((open_start, timestamp))
            open_start = None
    if open_start is not None and observed >= open_start:
        intervals.append((open_start, observed))
    if not intervals:
        return [{"start": _iso(started) or "", "end": _iso(observed) or ""}]
    intervals.sort(key=lambda item: item[0])
    merged: list[tuple[datetime, datetime]] = []
    for current in intervals:
        if merged and current[0] <= merged[-1][1] + timedelta(seconds=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], current[1]))
        else:
            merged.append(current)
    return [
        {"start": _iso(start) or "", "end": _iso(end) or ""}
        for start, end in merged
        if end >= start
    ]


def _summary_counts(
    task: Task,
    counts: dict[str, Any],
    item_totals: dict[str, int],
) -> dict[str, int]:
    if task.task_type == "discovery":
        return {
            "processed": _as_int(counts.get("valid_urls"))
            + _as_int(counts.get("excluded_urls"))
            + _as_int(counts.get("failed_urls")),
            "valid": _as_int(counts.get("valid_urls")),
            "excluded": _as_int(counts.get("excluded_urls")),
            "failed": _as_int(counts.get("failed_urls")),
            "discovered_urls": _as_int(counts.get("discovered_urls")),
            "candidates": _as_int(counts.get("url_candidates")),
            "pending": _as_int(counts.get("pending_urls")),
        }
    processed = _as_int(counts.get("processed_products"))
    if processed == 0:
        processed = (
            item_totals["valid"] + item_totals["excluded"] + item_totals["failed"]
        )
    return {
        "processed": processed,
        "valid": _as_int(counts.get("valid_products"), item_totals["valid"]),
        "excluded": _as_int(
            counts.get("excluded_products"), item_totals["excluded"]
        ),
        "failed": _as_int(counts.get("failed_products"), item_totals["failed"]),
        "discovered_urls": _as_int(counts.get("discovered_urls")),
        "candidates": _as_int(counts.get("product_candidates"), processed),
        "pending": _as_int(counts.get("pending_products")),
    }


def _request_block(
    *,
    available: bool,
    reason: str | None,
    truncated: bool,
    summary: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "available": available,
        "reason": reason,
        "truncated": truncated,
    }
    if summary is not None:
        payload.update(summary)
    return payload


def _failure_payload(
    *,
    task: Task,
    result: dict[str, Any],
    counts: dict[str, int],
    items_path: Path,
    points: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool, int]:
    by_class: Counter[str] = Counter()
    result_classes = result.get("failure_classes")
    if isinstance(result_classes, dict):
        for key in ("transient", "permanent", "blocked", "unknown"):
            by_class[key] = _as_int(result_classes.get(key))
    item_classes: Counter[str] = Counter()
    by_reason: Counter[str] = Counter()
    samples: dict[str, str] = {}
    legacy_reasons = False
    skipped = 0
    seen_failure = False
    if items_path.is_file():
        for payload, ok in _iter_jsonl(items_path):
            if not ok or payload is None:
                skipped += 1
                continue
            item_type = payload.get("item_type")
            expected_type = "product"
            if item_type is not None and item_type != expected_type:
                continue
            if str(payload.get("state") or "").upper() != "FAILED":
                continue
            seen_failure = True
            item_result = payload.get("result")
            item_result = item_result if isinstance(item_result, dict) else {}
            failure_class = str(
                payload.get("failure_class")
                or item_result.get("failure_class")
                or "unknown"
            )
            if failure_class not in {"transient", "permanent", "blocked"}:
                failure_class = "unknown"
            item_classes[failure_class] += 1
            code = str(
                item_result.get("detail_code")
                or item_result.get("reason")
                or "unknown"
            )
            by_reason[code] += 1
            if code not in samples:
                samples[code] = str(
                    item_result.get("source_url")
                    or payload.get("url")
                    or ""
                )
            if not item_result.get("reason") and not item_result.get("detail_code"):
                legacy_reasons = True
    elif _as_int(counts.get("failed")) > 0:
        legacy_reasons = True

    if sum(item_classes.values()) > 0:
        by_class = item_classes
    total = max(_as_int(counts.get("failed")), sum(by_reason.values()))
    if total == 0:
        total = sum(by_class.values())
    if not by_class and total:
        by_class["unknown"] = total

    ordered = by_reason.most_common()
    top = ordered[:FAILURE_REASON_LIMIT]
    other = sum(count for _, count in ordered[FAILURE_REASON_LIMIT:])
    reason_rows = []
    for code, count in top:
        reason_rows.append(
            {
                "code": code,
                "label": _failure_label(code),
                "count": count,
                "share": round(count / total, 4) if total else 0,
                "sample_url": samples.get(code) or None,
            }
        )
    if other:
        reason_rows.append(
            {
                "code": "other",
                "label": "其他",
                "count": other,
                "share": round(other / total, 4) if total else 0,
                "sample_url": None,
            }
        )
    peaks = sorted(
        (
            {
                "start": point["start"],
                "failed": point["failed"],
            }
            for point in points
            if point["failed"] >= FAILURE_PEAK_MIN
        ),
        key=lambda item: item["failed"],
        reverse=True,
    )[:3]
    legacy = legacy_reasons or (seen_failure and not by_reason)
    return (
        {
            "total": total,
            "by_class": dict(by_class),
            "by_reason": reason_rows,
            "peaks": peaks,
        },
        legacy,
        skipped,
    )


def _diagnostic(
    *,
    failures: dict[str, Any],
    requests: dict[str, Any],
    summary: dict[str, int],
    terminal: bool,
    skipped_lines: int,
) -> dict[str, Any] | None:
    reasons = failures.get("by_reason") or []
    total = _as_int(failures.get("total"))
    if reasons and total:
        top = reasons[0]
        code = str(top.get("code") or "")
        if code in {"access_denied", "challenge", "challenge_unresolved", "http_403"}:
            return {
                "code": "access_blocked",
                "tone": "danger",
                "title": "失败集中在访问被拒绝",
                "detail": f"{total} 个失败中 {top.get('count')} 个为{top.get('label')}。",
                "action_view": "data_failed",
            }
    if requests.get("available") and _as_int(requests.get("rate_limited")) > 0:
        return {
            "code": "rate_limited",
            "tone": "warning",
            "title": "出现请求限流",
            "detail": f"本次运行记录了 {requests.get('rate_limited')} 次 429；请求失败与商品失败分开统计。",
            "action_view": "detail",
        }
    if reasons and total >= 10 and top.get("share", 0) >= 0.8:
        return {
            "code": "failure_concentrated",
            "tone": "warning",
            "title": f"失败集中在{top.get('label')}",
            "detail": f"{total} 个失败中 {top.get('count')} 个为{top.get('label')}。",
            "action_view": "data_failed",
        }
    if terminal and summary.get("pending", 0) > 0:
        return {
            "code": "pending_work",
            "tone": "warning",
            "title": "仍有待处理工作",
            "detail": f"运行已结束，但还有 {summary.get('pending')} 个候选未处理。",
            "action_view": "detail",
        }
    if requests.get("truncated"):
        return {
            "code": "request_log_truncated",
            "tone": "warning",
            "title": "请求日志已截断",
            "detail": "请求记录达到容量上限；图表只覆盖已记录的部分。",
            "action_view": "detail",
        }
    if skipped_lines:
        return {
            "code": "skipped_lines",
            "tone": "warning",
            "title": "部分日志行无法读取",
            "detail": f"聚合时跳过了 {skipped_lines} 行损坏或空记录。",
            "action_view": "detail",
        }
    return None


def _empty_response(
    task: Task,
    *,
    now: datetime,
    window_seconds: int | None,
    bucket_seconds: int,
) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "generated_at": _iso(now),
        "observed_at": _iso(now),
        "scope": {
            "task_type": task.task_type,
            "state": task.state,
            "started_at": None,
            "finished_at": None,
            "run_seconds": 0,
            "window_seconds": window_seconds,
            "bucket_seconds": bucket_seconds,
            "first_bucket_at": None,
            "last_bucket_at": None,
            "truncated": False,
        },
        "summary": {
            "processed": 0,
            "valid": 0,
            "excluded": 0,
            "failed": 0,
            "yield_rate": 0,
            "failure_rate": 0,
            "average_throughput_per_minute": 0,
            "recent_throughput_per_minute": 0,
            "discovered_urls": 0,
            "product_candidates": 0,
            "pending_products": 0,
            "coverage": {"status": "UNKNOWN", "label": "覆盖未知"},
        },
        "series": {"bucket_seconds": bucket_seconds, "points": []},
        "requests": {
            "available": False,
            "reason": "not_started",
            "truncated": False,
        },
        "active_intervals": [],
        "failures": {
            "total": 0,
            "by_class": {},
            "by_reason": [],
            "peaks": [],
        },
        "budget": {
            "max_products": task.limits.get("max_products"),
            "max_seconds": task.limits.get("max_seconds"),
            "max_urls": task.limits.get("max_urls"),
            "max_requests": task.limits.get("max_requests"),
            "used_products": 0,
            "used_seconds": 0,
            "used_urls": 0,
            "used_requests": None,
        },
        "data_quality": {
            "level": "empty",
            "skipped_lines": 0,
            "legacy_reasons": False,
        },
        "diagnostics": [],
    }


def build_analysis(
    task: Task,
    out_dir: str | Path,
    *,
    counts: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    window_seconds: int | None = None,
    bucket_seconds: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate one task run into the analysis response."""

    out_dir = Path(out_dir)
    counts = dict(counts or {})
    result = dict(result or _read_json(out_dir / "task-result.json"))
    now = (now or datetime.now(UTC)).astimezone(UTC)
    if task.state in {"DRAFT", "QUEUED"} or not task.started_at:
        resolved_bucket = _resolve_bucket(0, bucket_seconds)
        return _empty_response(
            task,
            now=now,
            window_seconds=window_seconds,
            bucket_seconds=resolved_bucket,
        )

    events_path = out_dir / "events.ndjson"
    items_path = out_dir / "items.jsonl"
    requests_path = out_dir / "requests.ndjson"
    skipped_lines = 0
    item_events: list[tuple[datetime, str]] = []
    run_events: list[tuple[datetime, str]] = []
    first_event_ts: datetime | None = None
    last_event_ts: datetime | None = None

    expected_item_type = "product"
    for payload, ok in _iter_jsonl(events_path):
        if not ok or payload is None:
            skipped_lines += 1
            continue
        timestamp = _parse_ts(payload.get("ts"))
        if timestamp is None:
            skipped_lines += 1
            continue
        first_event_ts = first_event_ts or timestamp
        if last_event_ts is None or timestamp > last_event_ts:
            last_event_ts = timestamp
        event = payload.get("event")
        if event == "item_finished":
            item_type = payload.get("item_type")
            if item_type is not None and item_type != expected_item_type:
                continue
            item_events.append((timestamp, str(payload.get("state") or "").upper()))
        elif event in {"task_started", "task_paused", "task_finished", "task_error"}:
            run_events.append((timestamp, str(event)))

    started = _parse_ts(task.started_at) or first_event_ts or _parse_ts(task.created_at)
    if started is None:
        resolved_bucket = _resolve_bucket(0, bucket_seconds)
        return _empty_response(
            task,
            now=now,
            window_seconds=window_seconds,
            bucket_seconds=resolved_bucket,
        )
    finished = _parse_ts(task.finished_at)
    observed = finished or last_event_ts or now
    observed = max(observed, started)
    run_seconds = _as_float(task.counters.get("run_seconds"))
    if run_seconds <= 0:
        run_seconds = max(0.0, (observed - started).total_seconds())
    resolved_bucket = _resolve_bucket(run_seconds, bucket_seconds)

    item_buckets: dict[datetime, dict[str, int]] = {}
    item_totals = {"valid": 0, "excluded": 0, "failed": 0}
    for timestamp, state in item_events:
        key = _bucket_start(timestamp, resolved_bucket)
        bucket = item_buckets.setdefault(
            key,
            {"processed": 0, "valid": 0, "excluded": 0, "failed": 0},
        )
        bucket["processed"] += 1
        if state == "DONE":
            bucket["valid"] += 1
            item_totals["valid"] += 1
        elif state == "EXCLUDED":
            bucket["excluded"] += 1
            item_totals["excluded"] += 1
        elif state == "FAILED":
            bucket["failed"] += 1
            item_totals["failed"] += 1

    summary_counts = _summary_counts(task, counts, item_totals)
    requests_available = requests_path.is_file()
    requests_reason: str | None = None
    requests_truncated = False
    request_total = request_retries = request_errors = request_rate_limited = 0
    request_status_classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "none": 0}
    request_buckets: dict[datetime, dict[str, int]] = {}
    last_request_ts: datetime | None = None
    if requests_available:
        for payload, ok in _iter_jsonl(requests_path):
            if not ok or payload is None:
                skipped_lines += 1
                continue
            if payload.get("event") == "truncated":
                requests_truncated = True
                continue
            timestamp = _parse_ts(payload.get("ts"))
            if timestamp is None:
                skipped_lines += 1
                continue
            if last_request_ts is None or timestamp > last_request_ts:
                last_request_ts = timestamp
            status = _as_int(payload.get("status"))
            attempt = max(1, _as_int(payload.get("attempt"), 1))
            request_total += 1
            if attempt > 1:
                request_retries += 1
            if status == 0:
                request_status_classes["none"] += 1
            elif 200 <= status < 300:
                request_status_classes["2xx"] += 1
            elif 300 <= status < 400:
                request_status_classes["3xx"] += 1
            elif 400 <= status < 500:
                request_status_classes["4xx"] += 1
            elif 500 <= status < 600:
                request_status_classes["5xx"] += 1
            else:
                request_status_classes["none"] += 1
            if status == 0 or status >= 400:
                request_errors += 1
            if status == 429:
                request_rate_limited += 1
            key = _bucket_start(timestamp, resolved_bucket)
            bucket = request_buckets.setdefault(
                key,
                {"requests": 0, "retries": 0, "errors": 0, "rate_limited": 0},
            )
            bucket["requests"] += 1
            if attempt > 1:
                bucket["retries"] += 1
            if status == 0 or status >= 400:
                bucket["errors"] += 1
            if status == 429:
                bucket["rate_limited"] += 1
        if not request_total:
            requests_available = False
            requests_reason = "empty"
        if last_request_ts is not None and last_request_ts > observed:
            observed = last_request_ts
    else:
        requests_reason = "legacy"

    request_summary = (
        {
            "total": request_total,
            "retries": request_retries,
            "errors": request_errors,
            "rate_limited": request_rate_limited,
            "status_classes": dict(request_status_classes),
            "average_per_minute": round(request_total / run_seconds * 60, 2)
            if run_seconds > 0
            else 0,
        }
        if requests_available
        else None
    )

    all_buckets = sorted(set(item_buckets) | set(request_buckets))
    points: list[dict[str, Any]] = []
    cumulative = {
        "processed": 0,
        "valid": 0,
        "excluded": 0,
        "failed": 0,
        "requests": 0,
        "retries": 0,
        "errors": 0,
        "rate_limited": 0,
    }
    for key in all_buckets:
        item = item_buckets.get(
            key, {"processed": 0, "valid": 0, "excluded": 0, "failed": 0}
        )
        request = request_buckets.get(key)
        cumulative["processed"] += item["processed"]
        cumulative["valid"] += item["valid"]
        cumulative["excluded"] += item["excluded"]
        cumulative["failed"] += item["failed"]
        point: dict[str, Any] = {
            "start": _iso(key),
            "end": _iso(key + timedelta(seconds=resolved_bucket)),
            "processed": item["processed"],
            "valid": item["valid"],
            "excluded": item["excluded"],
            "failed": item["failed"],
            "cumulative_processed": cumulative["processed"],
            "cumulative_valid": cumulative["valid"],
            "cumulative_excluded": cumulative["excluded"],
            "cumulative_failed": cumulative["failed"],
        }
        if requests_available:
            request = request or {
                "requests": 0,
                "retries": 0,
                "errors": 0,
                "rate_limited": 0,
            }
            cumulative["requests"] += request["requests"]
            cumulative["retries"] += request["retries"]
            cumulative["errors"] += request["errors"]
            cumulative["rate_limited"] += request["rate_limited"]
            point["requests"] = {
                "total": request["requests"],
                "retries": request["retries"],
                "errors": request["errors"],
                "rate_limited": request["rate_limited"],
            }
            point["cumulative_requests"] = {
                "total": cumulative["requests"],
                "retries": cumulative["retries"],
                "errors": cumulative["errors"],
                "rate_limited": cumulative["rate_limited"],
            }
        points.append(point)

    if points:
        last_end = _parse_ts(points[-1]["end"])
        if last_end is not None and observed < last_end:
            points[-1]["partial"] = True

    truncated = False
    if len(points) > MAX_POINTS:
        points = points[-MAX_POINTS:]
        truncated = True
    if window_seconds is not None:
        cutoff = _bucket_start(
            observed - timedelta(seconds=max(60, int(window_seconds))),
            resolved_bucket,
        )
        points = [
            point
            for point in points
            if (_parse_ts(point["start"]) or cutoff) >= cutoff
        ]

    recent_points = list(points)
    if recent_points and recent_points[-1].get("partial"):
        recent_points = recent_points[:-1]
    recent_slice = recent_points[-RECENT_BUCKETS:]
    recent_throughput = 0.0
    if recent_slice:
        recent_throughput = sum(point["processed"] for point in recent_slice) / (
            len(recent_slice) * resolved_bucket / 60
        )

    failures, legacy_reasons, failure_skipped = _failure_payload(
        task=task,
        result=result,
        counts=summary_counts,
        items_path=items_path,
        points=points,
    )
    skipped_lines += failure_skipped
    coverage = _coverage_payload(result)
    request_block = _request_block(
        available=requests_available,
        reason=requests_reason,
        truncated=requests_truncated,
        summary=request_summary if requests_available else None,
    )
    terminal = task.state in TERMINAL_STATES
    summary = {
        "processed": summary_counts["processed"],
        "valid": summary_counts["valid"],
        "excluded": summary_counts["excluded"],
        "failed": summary_counts["failed"],
        "yield_rate": round(
            summary_counts["valid"] / summary_counts["processed"], 4
        )
        if summary_counts["processed"]
        else 0,
        "failure_rate": round(
            summary_counts["failed"] / summary_counts["processed"], 4
        )
        if summary_counts["processed"]
        else 0,
        "average_throughput_per_minute": round(
            summary_counts["processed"] / run_seconds * 60, 2
        )
        if run_seconds > 0
        else 0,
        "recent_throughput_per_minute": round(recent_throughput, 2),
        "recent_buckets": len(recent_slice),
        "discovered_urls": summary_counts["discovered_urls"],
        "product_candidates": summary_counts["candidates"],
        "pending_products": summary_counts["pending"],
        "coverage": coverage,
    }
    diagnostics = []
    diagnostic = _diagnostic(
        failures=failures,
        requests=request_block,
        summary=summary_counts,
        terminal=terminal,
        skipped_lines=skipped_lines,
    )
    if diagnostic is not None:
        diagnostics.append(diagnostic)
    data_quality_level = "full"
    if not points:
        data_quality_level = "empty"
    elif skipped_lines or truncated or requests_truncated:
        data_quality_level = "partial"
    elif legacy_reasons:
        data_quality_level = "legacy"

    first_bucket = points[0]["start"] if points else None
    last_bucket = points[-1]["start"] if points else None
    used_requests = (
        _as_int(request_summary.get("total"))
        if requests_available and request_summary
        else None
    )
    return {
        "task_id": task.task_id,
        "generated_at": _iso(now),
        "observed_at": _iso(observed),
        "scope": {
            "task_type": task.task_type,
            "state": task.state,
            "started_at": _iso(started),
            "finished_at": _iso(finished),
            "run_seconds": int(run_seconds),
            "window_seconds": window_seconds,
            "bucket_seconds": resolved_bucket,
            "first_bucket_at": first_bucket,
            "last_bucket_at": last_bucket,
            "truncated": truncated,
        },
        "summary": summary,
        "series": {"bucket_seconds": resolved_bucket, "points": points},
        "requests": request_block,
        "active_intervals": _active_intervals(started, observed, run_events),
        "failures": failures,
        "budget": {
            "max_products": task.limits.get("max_products"),
            "max_seconds": task.limits.get("max_seconds"),
            "max_urls": task.limits.get("max_urls"),
            "max_requests": task.limits.get("max_requests"),
            "used_products": summary_counts["processed"],
            "used_seconds": int(run_seconds),
            "used_urls": summary_counts["discovered_urls"]
            if task.task_type != "discovery"
            else summary_counts["candidates"],
            "used_requests": used_requests,
        },
        "data_quality": {
            "level": data_quality_level,
            "skipped_lines": skipped_lines,
            "legacy_reasons": legacy_reasons,
        },
        "diagnostics": diagnostics,
    }


def analysis_fingerprint(
    task: Task,
    out_dir: str | Path,
    *,
    counts: dict[str, Any],
    window_seconds: int | None,
    bucket_seconds: int | None,
) -> str:
    out_dir = Path(out_dir)
    stats: list[tuple[str, int | None, int | None]] = []
    for name in ("events.ndjson", "items.jsonl", "requests.ndjson", "task-result.json"):
        path = out_dir / name
        try:
            stat = path.stat()
        except OSError:
            stats.append((name, None, None))
        else:
            stats.append((name, stat.st_mtime_ns, stat.st_size))
    payload = {
        "task_id": task.task_id,
        "state": task.state,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "counts": counts,
        "window_seconds": window_seconds,
        "bucket_seconds": bucket_seconds,
        "stats": stats,
    }
    return hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def analysis_etag(fingerprint: str) -> str:
    return f'"{fingerprint}"'


def build_analysis_cached(
    task: Task,
    out_dir: str | Path,
    *,
    counts: dict[str, Any],
    result: dict[str, Any],
    window_seconds: int | None,
    bucket_seconds: int | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    fingerprint = analysis_fingerprint(
        task,
        out_dir,
        counts=counts,
        window_seconds=window_seconds,
        bucket_seconds=bucket_seconds,
    )
    with _CACHE_LOCK:
        cached = _CACHE.get(fingerprint)
        if cached is not None:
            _CACHE.move_to_end(fingerprint)
            return cached
    built = build_analysis(
        task,
        out_dir,
        counts=counts,
        result=result,
        window_seconds=window_seconds,
        bucket_seconds=bucket_seconds,
        now=now,
    )
    with _CACHE_LOCK:
        _CACHE[fingerprint] = built
        _CACHE.move_to_end(fingerprint)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return built
