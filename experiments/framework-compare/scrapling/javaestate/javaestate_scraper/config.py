"""Stable configuration for the javaestate.com Scrapling plan."""

from __future__ import annotations

PLAN_ID = "javaestate-us-scrapling"
PLAN_VERSION = "2026.11.19-2"
SCHEMA_VERSION = "1.0"

SITE_NAME = "Java Estate Roastery"
ENTRY_URL = "https://javaestate.com/"
ORIGIN = "https://javaestate.com"
ALLOWED_HOSTS = {"javaestate.com", "www.javaestate.com"}
ROBOTS_URL = "https://javaestate.com/robots.txt"
SITEMAP_INDEX_URL = "https://javaestate.com/sitemap.xml"

MARKET = "US"
LOCALE = "en-US"
CURRENCY_EXPECTED = "USD"

STORE_NAME_TOKENS = {
    "java estate",
    "java estate roastery",
    "javaestate",
    "javaestate.com",
    "www.javaestate.com",
}

DEFAULT_MAX_PRODUCTS = 30
DEFAULT_MAX_SECONDS = 600
DEFAULT_DELAY_SECONDS = 1.1
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_MAX_RETRY_AFTER = 60

CSV_COLUMNS = [
    "name",
    "price_amount",
    "price_currency",
    "primary_image_url",
    "description_html",
    "category",
    "brand",
    "attributes",
    "source_url",
    "description_format",
    "description_status",
    "partial_reason",
    "missing_reasons",
    "market",
    "locale",
    "availability",
    "tax_basis",
    "price_basis",
    "task_id",
    "plan_id",
    "plan_version",
    "extracted_at",
]
