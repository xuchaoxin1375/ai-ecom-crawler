"""Shopify public product JSON source.

The module deliberately stays at the product-source boundary:

* the rule declares a ``product_source`` section;
* the runner uses this module to turn ``/products.json`` entries into
  :class:`~ecom_crawler.executor.extract.ExtractedProduct` values and prefetch
  payloads;
* the existing HTML extractors remain the fallback for descriptions and for
  products when the JSON endpoint is blocked.

It does not fetch pages, own work items or write task output.  Keeping those
responsibilities in the runner preserves the task ledger, retries, budgets and
recovery semantics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from ecom_crawler.executor.extract import ExtractedProduct
from ecom_crawler.executor.normalize import (
    clean_description,
    clean_name,
    clean_text,
    parse_number,
)

SUPPORTED_TYPES = {"shopify_json"}
SUPPORTED_DESCRIPTION_ENGINES = {"static", "browser"}
SUPPORTED_PRICE_MODES = {"min_positive", "first", "product_price"}
CORE_FIELDS = ("name", "price.amount", "price.currency", "primary_image_url", "source_url")
JSON_FIELD_SOURCE = "shopify_json"


class ShopifySourceError(ValueError):
    """A product source entry cannot be converted into a product record."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class ShopifyProductSource:
    """Validated runtime view of a rule's ``product_source`` section."""

    url: str
    product_url_template: str
    page_size: int = 250
    max_pages: int = 1
    currency: str = ""
    description_min_chars: int = 200
    description_fallback_engine: str | None = None
    fallback_concurrency: int = 1
    price_mode: str = "min_positive"

    @classmethod
    def from_rule(cls, rule: Any) -> ShopifyProductSource | None:
        raw = rule.raw.get("product_source")
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ShopifySourceError("invalid_product_source", "must be a mapping")
        source_type = str(raw.get("type") or "")
        if source_type not in SUPPORTED_TYPES:
            raise ShopifySourceError(
                "unsupported_product_source",
                f"unsupported type {source_type!r}; supported: {sorted(SUPPORTED_TYPES)}",
            )

        entry_url = str(rule.entry_url)
        parsed_entry = urlparse(entry_url)
        origin = f"{parsed_entry.scheme.lower()}://{parsed_entry.netloc.lower()}"
        if not parsed_entry.scheme or not parsed_entry.netloc:
            raise ShopifySourceError(
                "invalid_entry_url", f"entry URL is not absolute: {entry_url!r}"
            )

        url = str(raw.get("url") or f"{origin}/products.json")
        url = urljoin(f"{origin}/", url) if not urlparse(url).netloc else url
        product_url_template = str(
            raw.get("product_url_template") or f"{origin}/products/{{handle}}"
        )
        if not urlparse(product_url_template).netloc:
            product_url_template = urljoin(f"{origin}/", product_url_template)

        description = raw.get("description") or {}
        if not isinstance(description, dict):
            raise ShopifySourceError(
                "invalid_description_config", "product_source.description must be a mapping"
            )
        fallback_engine = description.get("fallback_engine")
        if fallback_engine is not None:
            fallback_engine = str(fallback_engine).strip().lower()
            if fallback_engine not in SUPPORTED_DESCRIPTION_ENGINES:
                raise ShopifySourceError(
                    "invalid_fallback_engine",
                    f"unsupported description fallback engine {fallback_engine!r}",
                )

        variants = raw.get("variants") or {}
        if not isinstance(variants, dict):
            raise ShopifySourceError(
                "invalid_variants_config", "product_source.variants must be a mapping"
            )
        price_mode = str(variants.get("price") or "min_positive")
        if price_mode not in SUPPORTED_PRICE_MODES:
            raise ShopifySourceError(
                "invalid_price_mode",
                f"unsupported variants.price {price_mode!r}; "
                f"supported: {sorted(SUPPORTED_PRICE_MODES)}",
            )

        site_currency = str(rule.site.get("currency") or "")
        currency = str(raw.get("currency") or site_currency)
        if site_currency and currency != site_currency:
            raise ShopifySourceError(
                "currency_mismatch",
                f"product_source.currency={currency!r} does not match "
                f"site.currency={site_currency!r}",
            )

        return cls(
            url=url,
            product_url_template=product_url_template,
            page_size=int(raw.get("page_size", 250)),
            max_pages=int(raw.get("max_pages", 1)),
            currency=currency,
            description_min_chars=int(description.get("min_chars", 200)),
            description_fallback_engine=fallback_engine,
            fallback_concurrency=int(description.get("fallback_concurrency", 1)),
            price_mode=price_mode,
        )

    def products(self, payload: Any) -> list[dict[str, Any]]:
        """Return the product list from a ``/products.json`` body."""
        value = payload.get("products") if isinstance(payload, dict) else payload
        if value is None:
            raise ShopifySourceError("products_missing", "payload has no products list")
        if not isinstance(value, list):
            raise ShopifySourceError(
                "products_not_list", "products must be a JSON array"
            )
        return [item for item in value if isinstance(item, dict)]

    def next_page_url(self, url: str, page: int) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["page"] = str(page)
        query["limit"] = str(self.page_size)
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(query, doseq=True),
                "",
            )
        )

    def first_page_url(self) -> str:
        """Include ``limit`` on the first request.

        Shopify defaults to 30 products when ``limit`` is omitted; relying on
        the default would make the configured 250-item page size ineffective.
        """
        return self.next_page_url(self.url, 1)

    def to_extracted(self, entry: dict[str, Any], *, base_url: str) -> ExtractedProduct:
        """Map one Shopify product entry to the shared product value model."""
        name = clean_name(
            clean_text(entry.get("title")),
            page_url=base_url,
        )
        if not name:
            raise ShopifySourceError("missing_name", "product has no title")
        handle = clean_text(entry.get("handle"))
        if not handle:
            raise ShopifySourceError("missing_handle", "product has no handle")

        source_url = self._source_url(handle, entry.get("id"), base_url=base_url)
        price = self._price(entry)
        if price is None or price <= 0:
            raise ShopifySourceError(
                "missing_price", "product has no positive variant or product price"
            )
        image = self._image(entry, base_url=base_url)
        description_html = clean_description(str(entry.get("body_html") or ""))
        description_text = clean_text(description_html)
        description_status = self._description_status(len(description_text))
        partial_reason = (
            "shopify_json_description_short"
            if description_status == "partial"
            else None
        )
        values = {
            "name": name,
            "price.amount": price,
            "price.currency": self.currency,
            "primary_image_url": image,
            "description_html": description_html,
            "category": clean_text(entry.get("product_type")),
            "brand": clean_text(entry.get("vendor")),
            "options": self._options(entry),
            "source_url": source_url,
        }
        sources = {
            field: JSON_FIELD_SOURCE
            for field, value in values.items()
            if value not in (None, "")
        }
        sources["description_html"] = f"{JSON_FIELD_SOURCE}.body_html"
        extras = {
            "price.amount": {
                "displayed": price,
                "basis": "unspecified",
            },
            "description_html": {
                "text_chars": len(description_text),
                "audit": {},
            },
        }
        return ExtractedProduct(
            values=values,
            sources=sources,
            extras=extras,
            description_status=description_status,
            partial_reason=partial_reason,
            missing_reasons=_missing_reasons(values),
        )

    def prefetch(self, product: ExtractedProduct) -> dict[str, Any]:
        """Return the bounded payload stored on a product work item.

        A partial description is at most ``description_min_chars - 1`` visible
        characters, so keeping it in the ledger is bounded.  Long descriptions
        are never prefetched; those products are committed directly.
        """
        return {
            "values": dict(product.values),
            "sources": dict(product.sources),
            "extras": dict(product.extras),
            "description_status": product.description_status,
            "partial_reason": product.partial_reason,
            "missing_reasons": dict(product.missing_reasons),
            "min_chars": self.description_min_chars,
        }

    def from_prefetch(self, payload: dict[str, Any]) -> ExtractedProduct:
        values = payload.get("values")
        if not isinstance(values, dict):
            raise ShopifySourceError(
                "invalid_prefetch", "shopify_prefetch.values must be a mapping"
            )
        return ExtractedProduct(
            values=dict(values),
            sources=dict(payload.get("sources") or {}),
            extras=dict(payload.get("extras") or {}),
            description_status=str(payload.get("description_status") or "not_provided"),
            partial_reason=payload.get("partial_reason"),
            missing_reasons=dict(payload.get("missing_reasons") or {}),
        )

    def merge(
        self, json_product: ExtractedProduct, html_product: ExtractedProduct
    ) -> ExtractedProduct:
        """Merge JSON-first fields with the HTML fallback description."""
        values = dict(html_product.values)
        sources = dict(html_product.sources)
        extras = dict(html_product.extras)

        for key in (
            "name",
            "price.amount",
            "price.currency",
            "primary_image_url",
            "category",
            "brand",
            "options",
            "source_url",
        ):
            value = json_product.values.get(key)
            if value in (None, ""):
                continue
            values[key] = value
            sources[key] = json_product.sources.get(key, JSON_FIELD_SOURCE)
            if key == "price.amount":
                extras[key] = json_product.extras.get(key, {})

        json_description = str(json_product.values.get("description_html") or "")
        html_description = str(html_product.values.get("description_html") or "")
        if len(clean_text(html_description)) > len(clean_text(json_description)):
            values["description_html"] = html_description
            sources["description_html"] = html_product.sources.get(
                "description_html", "html"
            )
            extras["description_html"] = html_product.extras.get(
                "description_html", {}
            )
            description_status = html_product.description_status
            partial_reason = html_product.partial_reason
        else:
            values["description_html"] = json_description
            sources["description_html"] = json_product.sources.get(
                "description_html", f"{JSON_FIELD_SOURCE}.body_html"
            )
            extras["description_html"] = json_product.extras.get(
                "description_html", {}
            )
            description_status = json_product.description_status
            partial_reason = json_product.partial_reason

        if description_status != "complete" and not partial_reason:
            partial_reason = "description_below_min_chars"
        return ExtractedProduct(
            values=values,
            sources=sources,
            extras=extras,
            description_status=description_status,
            partial_reason=partial_reason,
            missing_reasons=_missing_reasons(values),
        )

    def mark_fallback_failed(
        self, product: ExtractedProduct, reason: str
    ) -> ExtractedProduct:
        values = dict(product.values)
        description_status = product.description_status
        if description_status == "complete":
            description_status = "partial"
        return ExtractedProduct(
            values=values,
            sources=dict(product.sources),
            extras=dict(product.extras),
            description_status=description_status,
            partial_reason=f"description_fallback_failed:{reason}",
            missing_reasons=dict(product.missing_reasons),
        )

    def _source_url(self, handle: str, product_id: Any, *, base_url: str) -> str:
        try:
            rendered = self.product_url_template.format(
                handle=handle, id=product_id, product_id=product_id
            )
        except KeyError as exc:
            raise ShopifySourceError(
                "invalid_product_url_template",
                f"unknown placeholder {exc.args[0]!r}",
            ) from exc
        if not urlparse(rendered).netloc:
            rendered = urljoin(base_url, rendered)
        return rendered

    def _price(self, entry: dict[str, Any]) -> float | None:
        variants = entry.get("variants")
        variant_prices: list[float] = []
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                price = parse_number(variant.get("price"))
                if price is not None and price > 0:
                    variant_prices.append(price)
        product_price = parse_number(entry.get("price"))
        if self.price_mode == "product_price":
            return product_price or (min(variant_prices) if variant_prices else None)
        if self.price_mode == "first":
            return variant_prices[0] if variant_prices else product_price
        return min(variant_prices) if variant_prices else product_price

    def _image(self, entry: dict[str, Any], *, base_url: str) -> str:
        images = entry.get("images")
        if isinstance(images, list):
            for image in images:
                if isinstance(image, dict) and image.get("src"):
                    return urljoin(base_url, str(image["src"]))
                if isinstance(image, str) and image:
                    return urljoin(base_url, image)
        featured = entry.get("featured_image")
        if isinstance(featured, str) and featured:
            return urljoin(base_url, featured)
        image = entry.get("image")
        if isinstance(image, dict) and image.get("src"):
            return urljoin(base_url, str(image["src"]))
        if isinstance(image, str) and image:
            return urljoin(base_url, image)
        return ""

    def _options(self, entry: dict[str, Any]) -> str:
        titles: list[str] = []
        variants = entry.get("variants")
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                title = clean_text(variant.get("title"))
                if title and title not in titles:
                    titles.append(title)
        return " | ".join(titles)

    def _description_status(self, length: int) -> str:
        if length >= self.description_min_chars:
            return "complete"
        if length:
            return "partial"
        return "not_provided"


def _missing_reasons(values: dict[str, Any]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for field in CORE_FIELDS:
        if not values.get(field):
            reasons[field] = "NOT_PROVIDED"
    return reasons


def parse_products_payload(body: bytes) -> Any:
    """Decode a public JSON body with a stable error type."""
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShopifySourceError("invalid_json", str(exc)) from exc
