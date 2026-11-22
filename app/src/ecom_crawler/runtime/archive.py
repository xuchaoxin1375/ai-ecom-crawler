"""Local page archive for rule review, replay and offline collection.

The archive is intentionally simple: one gzip-compressed body and one JSON
metadata file per normalized URL, plus an append-only JSONL index.  Raw HTML is
stored, but image/font assets are not; the archive is for re-running extraction
and discovery, not for rendering a pixel-identical page offline.

Modes:

- ``off``: no writes and no reads.
- ``sample``: bounded writes (default 20 pages); reads allowed when reuse is on.
- ``full``: every successful response is written; strict offline replay is
  allowed only in this mode.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .fetcher import UnsupportedAdvanceError
from .models import FetchResult

ARCHIVE_MODES = {"off", "sample", "full"}


class ArchiveError(RuntimeError):
    """Base archive error."""


class ArchiveMissError(ArchiveError):
    """A strict offline replay could not find the requested URL."""


def normalize_archive_mode(value: str | None) -> str:
    mode = str(value or "off").strip().lower()
    if mode not in ARCHIVE_MODES:
        raise ArchiveError(f"unsupported archive mode: {value!r}")
    return mode


def archive_url_key(url: str) -> str:
    parts = urlsplit(url)
    normalized = urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path or "/",
            parts.query,
            "",
        )
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def archive_host(url: str) -> str:
    host = urlsplit(url).hostname or "unknown"
    return "".join(char if char.isalnum() or char in ".-" else "_" for char in host)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class ArchiveStats:
    mode: str
    root: str
    sample_limit: int
    pages: int = 0
    bytes: int = 0
    hits: int = 0
    misses: int = 0
    writes: int = 0
    skipped: int = 0
    skipped_reason: str | None = None
    limit_reached: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "root": self.root,
            "sample_limit": self.sample_limit,
            "pages": self.pages,
            "bytes": self.bytes,
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "skipped": self.skipped,
            "skipped_reason": self.skipped_reason,
            "limit_reached": self.limit_reached,
            "errors": self.errors[-5:],
        }


class ArchiveStore:
    """Read and write one shared archive root."""

    def __init__(
        self,
        root: str | Path,
        *,
        mode: str = "off",
        sample_limit: int = 20,
        max_bytes: int | None = None,
        task_id: str | None = None,
    ) -> None:
        self.root = Path(root)
        self.mode = normalize_archive_mode(mode)
        self.sample_limit = max(0, int(sample_limit))
        self.max_bytes = max(0, int(max_bytes)) if max_bytes is not None else None
        self.task_id = task_id
        self._lock = threading.RLock()
        self._saved = 0
        self._bytes = 0
        self._stats = ArchiveStats(
            mode=self.mode,
            root=str(self.root),
            sample_limit=self.sample_limit,
        )
        if self.mode != "off":
            self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def body_path(self, url: str) -> Path:
        return self.root / archive_host(url) / f"{archive_url_key(url)}.html.gz"

    def meta_path(self, url: str) -> Path:
        return self.root / archive_host(url) / f"{archive_url_key(url)}.json"

    # ------------------------------------------------------------------ reads
    def lookup(self, url: str) -> tuple[bytes, dict[str, Any]] | None:
        if self.mode == "off":
            return None
        body_path = self.body_path(url)
        meta_path = self.meta_path(url)
        if not body_path.is_file() or not meta_path.is_file():
            with self._lock:
                self._stats.misses += 1
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = gzip.decompress(body_path.read_bytes())
        except (OSError, json.JSONDecodeError, gzip.BadGzipFile):
            with self._lock:
                self._stats.misses += 1
            return None
        with self._lock:
            self._stats.hits += 1
        return body, meta

    # ------------------------------------------------------------------ writes
    def save(
        self,
        url: str,
        result: FetchResult,
        *,
        engine: str = "",
    ) -> bool:
        if self.mode == "off" or not result.body:
            return False
        status = int(result.status or 0)
        if not (200 <= status < 300 or status == 404):
            return False
        with self._lock:
            if self.mode == "sample" and self._saved >= self.sample_limit:
                self._stats.skipped += 1
                self._stats.skipped_reason = "sample_limit"
                self._stats.limit_reached = True
                return False
        body = bytes(result.body)
        compressed = gzip.compress(body, compresslevel=6)
        with self._lock:
            if self.max_bytes is not None and self._bytes + len(compressed) > self.max_bytes:
                self._stats.skipped += 1
                self._stats.skipped_reason = "max_bytes"
                self._stats.limit_reached = True
                return False
        body_path = self.body_path(url)
        meta_path = self.meta_path(url)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = body_path.with_suffix(".tmp")
        try:
            tmp_path.write_bytes(compressed)
            os.replace(tmp_path, body_path)
            meta = {
                "url": url,
                "final_url": result.url or url,
                "status": int(result.status or 0),
                "content_type": str(result.meta.get("content_type") or ""),
                "sha256": hashlib.sha256(body).hexdigest(),
                "raw_bytes": len(body),
                "stored_bytes": len(compressed),
                "fetched_at": _utc_now(),
                "engine": engine,
                "task_id": self.task_id,
                "body_path": str(body_path),
            }
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self._append_index(meta)
        except OSError as exc:
            with self._lock:
                self._stats.errors.append(f"{type(exc).__name__}: {exc}")
            return False
        with self._lock:
            self._saved += 1
            self._bytes += len(compressed)
            self._stats.pages = self._saved
            self._stats.bytes = self._bytes
            self._stats.writes += 1
        return True

    def _append_index(self, meta: dict[str, Any]) -> None:
        line = json.dumps(meta, ensure_ascii=False, sort_keys=True) + "\n"
        index = self.root / "index.jsonl"
        with self._lock, index.open("a", encoding="utf-8") as handle:
            handle.write(line)

    # ------------------------------------------------------------------- stats
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return self._stats.to_dict()

    def scan(self) -> dict[str, Any]:
        """Summarize an archive root without loading page bodies."""
        pages = 0
        total = 0
        if not self.root.is_dir():
            return {"pages": 0, "bytes": 0}
        for path in self.root.rglob("*.html.gz"):
            pages += 1
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return {"pages": pages, "bytes": total}


class ArchiveFetcher:
    """Wrap a runtime fetcher with archive write/replay behavior."""

    def __init__(
        self,
        inner: Any,
        store: ArchiveStore,
        *,
        offline: bool = False,
        reuse: bool = False,
    ) -> None:
        self.inner = inner
        self.store = store
        self.offline = bool(offline)
        self.reuse = bool(reuse)
        if self.offline and store.mode != "full":
            raise ArchiveError("strict offline replay requires archive mode=full")
        try:
            self._engine = str(inner.describe().get("engine") or "")
        except Exception:  # noqa: BLE001 - engine label is best effort
            self._engine = ""

    @property
    def requests(self) -> int:
        return int(getattr(self.inner, "requests", 0))

    @property
    def retries(self) -> int:
        return int(getattr(self.inner, "retries", 0))

    @property
    def thread_affine(self) -> bool:
        return bool(getattr(self.inner, "thread_affine", False))

    def get(self, url: str, *, item_type: str | None = None) -> FetchResult:
        cached = self.store.lookup(url) if (self.offline or self.reuse) else None
        if cached is not None:
            body, meta = cached
            return FetchResult(
                status=int(meta.get("status") or 200),
                url=str(meta.get("final_url") or url),
                body=body,
                meta={
                    "archived": True,
                    "content_type": meta.get("content_type") or "",
                    "archive_path": meta.get("body_path"),
                },
            )
        if self.offline:
            raise ArchiveMissError(f"archive miss for {url}")
        result = self.inner.get(url, item_type=item_type)
        self.store.save(url, result, engine=self._engine)
        return result

    def get_listing(
        self,
        url: str,
        *,
        advance: dict[str, Any],
        item_selector: str | None = None,
        item_type: str | None = None,
    ) -> FetchResult:
        cached = self.store.lookup(url) if (self.offline or self.reuse) else None
        if cached is not None:
            body, meta = cached
            return FetchResult(
                status=int(meta.get("status") or 200),
                url=str(meta.get("final_url") or url),
                body=body,
                meta={
                    "archived": True,
                    "content_type": meta.get("content_type") or "",
                    "archive_path": meta.get("body_path"),
                },
            )
        if self.offline:
            raise ArchiveMissError(f"archive miss for listing {url}")
        method = getattr(self.inner, "get_listing", None)
        if not callable(method):
            raise UnsupportedAdvanceError(
                "inner fetcher does not support listing advance"
            )
        result = method(
            url,
            advance=advance,
            item_selector=item_selector,
            item_type=item_type,
        )
        self.store.save(url, result, engine=self._engine)
        return result

    def describe(self) -> dict[str, Any]:
        info = self.inner.describe() if hasattr(self.inner, "describe") else {}
        info = dict(info)
        info["archive"] = self.store.stats()
        info["archive_offline"] = self.offline
        info["archive_reuse"] = self.reuse
        return info

    def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if callable(close):
            close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_strings(item))
        return result
    return []


def rule_sample_urls(rule: Any, *, limit: int) -> list[str]:
    """Collect entry/listing/sample URLs declared by a rule for prefetch."""
    raw = getattr(rule, "raw", {}) if not isinstance(rule, dict) else rule
    candidates: list[str] = []
    site = raw.get("site") if isinstance(raw.get("site"), dict) else {}
    candidates.extend(_strings(site.get("entry_urls")))
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    candidates.extend(_strings(evidence.get("sample_urls")))
    discovery = raw.get("discovery") if isinstance(raw.get("discovery"), dict) else {}
    candidates.extend(_strings(discovery.get("entry_url")))
    sources = discovery.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            candidates.extend(_strings(source.get("url")))
            candidates.extend(_strings(source.get("urls")))
    urls: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if not url.startswith(("http://", "https://")):
            continue
        key = archive_url_key(url)
        if key in seen:
            continue
        seen.add(key)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def prefetch_rule_samples(
    rule: Any,
    root: str | Path,
    *,
    proxy: str | None = None,
    limit: int = 20,
    timeout_ms: int = 45000,
) -> dict[str, Any]:
    """Fetch declared sample URLs once and store them for later replay.

    Failures are recorded in ``errors`` but do not fail the build; host
    validation remains the authoritative gate.
    """
    root = Path(root)
    store = ArchiveStore(
        root,
        mode="sample",
        sample_limit=max(1, limit),
        task_id="build-prefetch",
    )
    urls = rule_sample_urls(rule, limit=limit)
    if not urls:
        return store.stats()
    try:
        from scrapling.fetchers import FetcherSession
    except Exception as exc:  # noqa: BLE001 - optional import boundary
        store._stats.errors.append(f"prefetch unavailable: {type(exc).__name__}: {exc}")
        return store.stats()
    try:
        with FetcherSession(
            impersonate="chrome",
            timeout=max(1, timeout_ms) / 1000,
            retries=1,
            proxy=proxy,
        ) as session:
            for url in urls:
                body_path = store.body_path(url)
                if body_path.is_file():
                    continue
                try:
                    response = session.get(
                        url,
                        timeout=max(1, timeout_ms) / 1000,
                        retries=1,
                        follow_redirects=True,
                    )
                except Exception as exc:  # noqa: BLE001 - per-URL boundary
                    store._stats.errors.append(f"{url}: {type(exc).__name__}: {exc}")
                    continue
                status = int(getattr(response, "status", 0) or 0)
                body = getattr(response, "body", b"") or b""
                if isinstance(body, str):
                    body = body.encode("utf-8")
                headers = getattr(response, "headers", {}) or {}
                content_type = ""
                try:
                    content_type = str(
                        headers.get("content-type")
                        or headers.get("Content-Type")
                        or ""
                    )
                except AttributeError:
                    content_type = ""
                store.save(
                    url,
                    FetchResult(
                        status=status,
                        url=str(getattr(response, "url", url)),
                        body=bytes(body),
                        meta={"content_type": content_type},
                    ),
                    engine="static-prefetch",
                )
    except Exception as exc:  # noqa: BLE001 - prefetch must not fail the build
        store._stats.errors.append(f"prefetch session: {type(exc).__name__}: {exc}")
    return store.stats()

