"""Robots.txt probing: retain only Sitemap declarations.

The project does not use robots.txt as an access gate. Every stage may fetch it
opportunistically, but only ``Sitemap:`` lines are kept; every other line is
discarded without parsing, storing or feeding it to a model.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse, urlunparse

MAX_SITEMAPS = 20


def robots_url_for(url: str) -> str:
    """Return the robots.txt URL for an HTTP(S) entry URL."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"not an HTTP(S) URL: {url}")
    return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))


def extract_sitemaps(
    body: bytes | str, *, base_url: str, limit: int = MAX_SITEMAPS
) -> list[str]:
    """Return de-duplicated ``Sitemap:`` values without retaining other lines."""
    candidates: list[str] = []
    parsed = urlparse(base_url)
    origin = urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
    for raw in body.splitlines():
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        line = line.strip().lstrip("\ufeff")
        if not line.lower().startswith("sitemap:"):
            continue
        value = line.split(":", 1)[1].strip()
        if not value:
            continue
        value = urljoin(origin or base_url, value)
        if value not in candidates:
            candidates.append(value)
        if len(candidates) >= limit:
            break
    return candidates
