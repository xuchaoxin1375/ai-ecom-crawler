"""Sampled content audit: compare rendered product text with rule extraction.

This is a diagnostic tool, not the batch extractor.  It renders a handful of
product pages, saves screenshots for human review, and reports visible blocks
that are not represented in the extracted description or other fields.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from scrapling.fetchers import FetcherSession

from .executor.extract import HtmlPage, _text_covered, extract_product
from .runtime.rule import load_rule

DEFAULT_CONTAINERS = (
    "#center_column",
    "main",
    '[itemtype*="Product"]',
    ".product-detail",
    "body",
)
DEFAULT_EXCLUDES = (
    "header, footer, nav, aside, .breadcrumb, .breadcrumb-box, .product-list, "
    ".products, .related, .reviews, #reviews, .newsletter, .cookie, "
    ".socialsharing_product, .Livraison1, .other-info, .product-navigation, "
    ".netreviews_reviews_section, .netreviews_review_part, #tabs-3, "
    "[id*='review'], [class*='review']"
)
SPEC_WORDS = re.compile(
    r"\b(composition|compositions|poids|hauteur|largeur|laize|matiere|matière|"
    r"dimensions?|entretien|proprietes|propriétés|style|couleur|couleurs|"
    r"grammage|diametre|diamètre|epaisseur|épaisseur)\b",
    re.IGNORECASE,
)
BOILERPLATE = re.compile(
    r"(ajouter au panier|add to cart|livraison|expédition|expedition|retour|"
    r"partager|newsletter|cookie|paiement|stock|quantité|quantity|prix|"
    r"réduction|reduction|voir plus|read more|avis|reviews?)",
    re.IGNORECASE,
)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def _extracted_text(product: Any) -> str:
    values = product.values
    parts = [
        _clean(str(values.get("description_html") or "")),
        str(values.get("name") or ""),
        str(values.get("brand") or ""),
        str(values.get("category") or ""),
        str(values.get("options") or ""),
        str(values.get("price.amount") or ""),
        str(values.get("price.currency") or ""),
    ]
    return " ".join(part for part in parts if part)


def _looks_like_product_content(text: str) -> bool:
    if SPEC_WORDS.search(text):
        return True
    return len(text) >= 80 and not BOILERPLATE.search(text)


def _fetch_static(url: str, timeout_s: float = 45.0) -> Any:
    with FetcherSession(impersonate="chrome", timeout=timeout_s, retries=0) as session:
        return session.get(url)


def _render_page(page: Any, url: str, timeout_ms: int) -> dict[str, Any]:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(800)
    container = next(
        (
            selector
            for selector in DEFAULT_CONTAINERS
            if page.query_selector(selector) is not None
        ),
        "body",
    )
    payload = page.evaluate(
        """
        ([containerSel, excludeSel, minChars]) => {
          const root = document.querySelector(containerSel) || document.body;
          const excludes = excludeSel.split(',').map(s => s.trim()).filter(Boolean);
          const nodes = root.querySelectorAll('p, li, dd, td, h1, h2, h3, h4, blockquote');
          const seen = new Set();
          const blocks = [];
          for (const el of nodes) {
            if (excludes.some(sel => { try { return el.closest(sel); } catch { return false; } })) continue;
            const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
            if (text.length < minChars) continue;
            if (seen.has(text)) continue;
            seen.add(text);
            blocks.push(text);
          }
          return {
            container: root.id ? '#' + root.id : (root.className || root.tagName),
            blocks,
          };
        }
        """,
        [container, DEFAULT_EXCLUDES, 20],
    )
    return {"container": payload["container"], "blocks": payload["blocks"]}


def _slug(url: str) -> str:
    parts = urlsplit(url)
    name = Path(parts.path).name or "page"
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"{name[:80]}-{digest}"


def audit_urls(
    rule_path: str | Path,
    urls: list[str],
    out_dir: str | Path,
    *,
    headless: bool = True,
    screenshots: bool = True,
    timeout_ms: int = 45000,
) -> dict[str, Any]:
    rule = load_rule(rule_path)
    plan = rule.product_plan()
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    shots = output / "screenshots"
    if screenshots:
        shots.mkdir(parents=True, exist_ok=True)

    from patchright.sync_api import sync_playwright

    results: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            for url in urls:
                started = time.monotonic()
                record: dict[str, Any] = {
                    "url": url,
                    "checked_at": datetime.now(UTC).isoformat(),
                }
                try:
                    static = _fetch_static(url, timeout_ms / 1000)
                    record["http_status"] = int(static.status)
                    if int(static.status) != 200:
                        record["error"] = f"http_{static.status}"
                        results.append(record)
                        continue
                    product = extract_product(
                        HtmlPage(static.body, static.url), plan
                    )
                    record["extraction"] = {
                        "name": product.values.get("name"),
                        "description_status": product.description_status,
                        "description_chars": len(
                            _clean(str(product.values.get("description_html") or ""))
                        ),
                        "description_audit": product.extras.get(
                            "description_html", {}
                        ).get("audit"),
                    }
                    rendered = _render_page(page, url, timeout_ms)
                    record["rendered"] = rendered
                    if screenshots:
                        shot_path = shots / f"{_slug(url)}.png"
                        page.screenshot(path=str(shot_path), full_page=True)
                        record["screenshot"] = str(shot_path)
                    extracted = _extracted_text(product)
                    flagged = []
                    for block in rendered["blocks"]:
                        if _text_covered(block, extracted):
                            continue
                        if not _looks_like_product_content(block):
                            continue
                        flagged.append({"text": block[:500], "chars": len(block)})
                    record["uncovered_blocks"] = flagged
                    record["elapsed_s"] = round(time.monotonic() - started, 2)
                except Exception as exc:  # noqa: BLE001 - audit boundary
                    record["error"] = f"{type(exc).__name__}: {exc}"
                results.append(record)
        finally:
            browser.close()

    summary = {
        "rule_id": rule.rule_id,
        "rule_version": rule.rule_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "pages": len(results),
        "errors": sum(1 for item in results if item.get("error")),
        "pages_with_uncovered": sum(
            1 for item in results if item.get("uncovered_blocks")
        ),
        "results": results,
    }
    (output / "visual-audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary
