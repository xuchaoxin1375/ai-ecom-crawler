#!/usr/bin/env python3
"""Minimal hybrid adapter for virtual-list discovery.

This is a C2 adapter prototype, not a declarative rule primitive. It launches a
browser, captures the visible virtual-list batch before each scroll, accumulates
stable item IDs, and emits NDJSON to stdout. The caller owns task state, budgets,
scope acceptance, product extraction and final acceptance.

Run:

    python adapter.py --context context.json

The context and event shapes are documented in README.md and
docs/19-采集规则与任务运行时.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ADAPTER_ID = "virtual-list-patchright"
ADAPTER_VERSION = "2026.11.22-1"


class ContextError(ValueError):
    """The task context is missing or invalid."""


class AdapterRuntimeError(RuntimeError):
    """The browser or page could not complete the requested collection."""


def emit(event: str, **payload: Any) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def positive_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContextError(f"expected a positive integer, got {value!r}")
    return value


def non_negative_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContextError(f"expected a non-negative integer, got {value!r}")
    return value


def load_context(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContextError(f"context file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContextError(f"context is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ContextError("context must be a JSON object")
    entry_url = str(data.get("entry_url") or "").strip()
    parsed = urlparse(entry_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ContextError("entry_url must be an absolute http(s) URL")
    advance = data.get("advance")
    if not isinstance(advance, dict):
        raise ContextError("advance must be an object")
    if not str(advance.get("item_selector") or "").strip():
        raise ContextError("advance.item_selector is required")
    return data


def compile_patterns(values: Any, field: str) -> list[re.Pattern[str]]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ContextError(f"scope.{field} must be a list")
    patterns: list[re.Pattern[str]] = []
    for value in values:
        try:
            patterns.append(re.compile(str(value)))
        except re.error as exc:
            raise ContextError(f"invalid scope.{field} pattern {value!r}: {exc}") from exc
    return patterns


def allowed_url(
    url: str,
    includes: list[re.Pattern[str]],
    excludes: list[re.Pattern[str]],
) -> bool:
    path = urlparse(url).path or "/"
    if includes and not any(pattern.search(path) for pattern in includes):
        return False
    return not any(pattern.search(url) for pattern in excludes)


def collect_script(selector: str, id_attribute: str) -> str:
    id_expr = (
        f"el.getAttribute({json.dumps(id_attribute)})"
        if id_attribute
        else "null"
    )
    return f"""() => Array.from(document.querySelectorAll({json.dumps(selector)})).map((el) => {{
  const href = el.getAttribute('href');
  let url = '';
  if (href) {{
    try {{ url = new URL(href, location.href).href; }} catch (e) {{ url = href; }}
  }}
  const explicit = {id_expr};
  const id = explicit || el.getAttribute('data-id') || el.getAttribute('data-product-id') || href || (el.textContent || '').trim();
  return {{ id: String(id || ''), url }};
}})"""


def capture(page: Any, script: str) -> list[dict[str, str]]:
    try:
        raw = page.evaluate(script)
    except Exception as exc:
        raise AdapterRuntimeError(f"cannot read items: {type(exc).__name__}: {exc}") from exc
    if not isinstance(raw, list):
        raise AdapterRuntimeError("page item collector did not return a list")
    items: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        item_id = str(entry.get("id") or "").strip()
        url = str(entry.get("url") or "").strip()
        if url or item_id:
            items.append({"id": item_id, "url": url})
    return items


def scroll_once(page: Any, advance: dict[str, Any]) -> None:
    mode = str(advance.get("mode") or "scroll").strip().lower()
    if mode not in {"auto", "scroll", "wheel"}:
        raise ContextError(f"unsupported advance.mode {mode!r}")
    if mode == "auto":
        mode = "scroll"
    container = str(advance.get("container") or "").strip()
    if container:
        locator = page.locator(container)
        if locator.count() == 0:
            raise AdapterRuntimeError(f"scroll container not found: {container}")
        target = locator.first
        if mode == "wheel":
            box = target.bounding_box()
            if not box:
                raise AdapterRuntimeError("scroll container has no bounding box")
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.wheel(0, 2000)
        else:
            target.evaluate("el => { el.scrollTop = el.scrollHeight; }")
        return
    if mode == "wheel":
        viewport = page.viewport_size or {"width": 1280, "height": 720}
        page.mouse.move(viewport["width"] / 2, viewport["height"] / 2)
        page.mouse.wheel(0, 2000)
    else:
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")


def run(context: dict[str, Any]) -> int:
    advance = context["advance"]
    limits = context.get("limits") or {}
    browser_options = context.get("browser") or {}
    scope = context.get("scope") or {}
    if not isinstance(limits, dict) or not isinstance(browser_options, dict) or not isinstance(scope, dict):
        raise ContextError("limits, browser and scope must be objects")

    entry_url = str(context["entry_url"])
    selector = str(advance["item_selector"])
    id_attribute = str(advance.get("id_attribute") or "data-id")
    settle_ms = non_negative_int(advance.get("settle_ms"), 200)
    no_new_stop = positive_int(advance.get("no_new_stop"), 2)
    max_items = positive_int(limits.get("max_items"), 100)
    max_batches = positive_int(limits.get("max_batches"), 10)
    max_seconds = positive_int(limits.get("max_seconds"), 60)
    timeout_ms = positive_int(browser_options.get("timeout_ms"), 30000)
    headless = bool(browser_options.get("headless", True))
    wait_state = str(browser_options.get("wait_state") or "attached").strip().lower()
    if wait_state not in {"attached", "visible", "hidden", "detached"}:
        raise ContextError(f"unsupported browser.wait_state {wait_state!r}")
    includes = compile_patterns(scope.get("include"), "include")
    excludes = compile_patterns(scope.get("exclude"), "exclude")
    script = collect_script(selector, id_attribute)

    emit(
        "start",
        adapter_id=ADAPTER_ID,
        adapter_version=ADAPTER_VERSION,
        plan_id=context.get("plan_id"),
        task_id=context.get("task_id"),
        entry_url=entry_url,
        limits={
            "max_items": max_items,
            "max_batches": max_batches,
            "max_seconds": max_seconds,
        },
    )

    from patchright.sync_api import sync_playwright

    started = time.monotonic()
    playwright = sync_playwright().start()
    browser = None
    seen: dict[str, dict[str, str]] = {}
    order: list[str] = []
    batches = 0
    stop = "MAX_BATCHES"
    start_url = entry_url
    final_url = entry_url
    urls: list[str] = []

    def capture_batch() -> int:
        nonlocal final_url
        final_url = str(page.url)
        if final_url != start_url and final_url not in urls and len(urls) < 10:
            urls.append(final_url)
        current = capture(page, script)
        added = 0
        for item in current:
            if len(seen) >= max_items:
                break
            url = item["url"]
            if not url or not allowed_url(url, includes, excludes):
                continue
            key = item["id"] or url
            if key in seen:
                continue
            seen[key] = item
            order.append(key)
            added += 1
        emit(
            "batch",
            batch=batches,
            ids=[item["id"] for item in current],
            new=added,
            total=len(seen),
            url=final_url,
        )
        return added

    try:
        browser = playwright.chromium.launch(headless=headless)
        browser_context = browser.new_context(
            locale=str(browser_options.get("locale") or "fr-FR"),
            timezone_id=str(browser_options.get("timezone") or "Europe/Paris"),
        )
        page = browser_context.new_page()
        page.goto(entry_url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_selector(selector, state=wait_state, timeout=timeout_ms)
        start_url = str(page.url)
        final_url = start_url

        added = capture_batch()
        stalls = 0 if added else 1
        while batches < max_batches and len(seen) < max_items:
            if time.monotonic() - started > max_seconds:
                stop = "MAX_SECONDS"
                break
            scroll_once(page, advance)
            if settle_ms:
                page.wait_for_timeout(settle_ms)
            batches += 1
            added = capture_batch()
            if added:
                stalls = 0
            else:
                stalls += 1
                if stalls >= no_new_stop:
                    stop = "NO_NEW_ITEMS"
                    break
        else:
            stop = "MAX_ITEMS" if len(seen) >= max_items else "MAX_BATCHES"
        if not seen:
            stop = "NO_ITEMS"
        discovered = [seen[key]["url"] for key in order]
        emit("discovered", count=len(discovered), urls=discovered)
        emit(
            "done",
            stop=stop,
            batches=batches,
            items=len(discovered),
            requests=1,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            start_url=start_url,
            final_url=final_url,
            url_changes=len(urls),
            urls=urls,
        )
        return 0
    finally:
        try:
            if browser is not None:
                browser.close()
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            print(f"cleanup warning: {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            playwright.stop()
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            print(f"cleanup warning: {type(exc).__name__}: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, type=Path, help="task context JSON file")
    args = parser.parse_args(argv)
    try:
        context = load_context(args.context)
    except ContextError as exc:
        emit("error", reason="invalid_context", failure_class="permanent", detail=str(exc))
        return 2
    try:
        return run(context)
    except ContextError as exc:
        emit("error", reason="invalid_context", failure_class="permanent", detail=str(exc))
        return 2
    except ImportError as exc:
        emit("error", reason="browser_unavailable", failure_class="permanent", detail=str(exc))
        return 3
    except Exception as exc:  # noqa: BLE001 - adapter boundary
        emit(
            "error",
            reason="adapter_failure",
            failure_class="transient",
            detail=f"{type(exc).__name__}: {exc}",
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
