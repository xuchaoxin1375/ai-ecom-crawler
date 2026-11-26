"""Shared backend test fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from threading import Thread
from typing import Any


@contextmanager
def serve_http_fixture(server: ThreadingHTTPServer) -> Iterator[None]:
    with server:
        # Shorten the shutdown poll in tests that create a server for each case.
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            yield
        finally:
            server.shutdown()
            thread.join(timeout=5)


def base_task(**overrides: Any) -> dict[str, Any]:
    task: dict[str, Any] = {
        "task_id": "task-001",
        "plan_id": "plan-001",
        "plan_version": "2026.11.21-1",
        "market": "GB",
        "locale": "en-GB",
        "state": "FINISHED",
        "stop_reason": "NATURAL_END",
        "started_at": "2026-11-21T00:00:00Z",
        "finished_at": "2026-11-21T00:05:00Z",
        "counts": {
            "discovered_urls": 10,
            "pending_navigation_entries": 0,
        },
    }
    task.update(overrides)
    return task


def candidate(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "source_url": "https://shop.example/products/shirt",
        "name": "Example Shirt",
        "price": {"amount": "29.00", "currency": "GBP"},
        "primary_image_url": "https://shop.example/images/shirt.jpg",
        "description_html": "<p>A shirt.</p>",
        "description_format": "html",
        "description_status": "COMPLETE",
        "categories": ["Shirts"],
        "brand": "Example",
        "options": [{"name": "Size", "values": ["S", "M"]}],
        "market": "GB",
        "locale": "en-GB",
        "availability": "IN_STOCK",
        "tax_basis": "INCLUSIVE",
        "extracted_at": "2026-11-21T00:01:00Z",
    }
    item.update(overrides)
    return item
