"""Bounded skatepro.es plan constants."""

from __future__ import annotations

PLAN_ID = "skatepro-es-scrapling"
PLAN_VERSION = "2026.11.19-2"

ORIGIN = "https://www.skatepro.es"
ALLOWED_HOSTS = {"www.skatepro.es", "skatepro.es"}
ENTRY_URL = f"{ORIGIN}/"
ROBOTS_URL = f"{ORIGIN}/robots.txt"
SITEMAP_URL = f"{ORIGIN}/sitemap.xml"

MARKET = "ES"
LOCALE = "es-ES"
CURRENCY = "EUR"

# robots.txt publishes `Crawl-delay: 10` for meta-externalagent; the D01 S2
# access boundary applies the same 10 s interval to this run.
DEFAULT_DELAY_SECONDS = 10.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_PRODUCTS = 30
DEFAULT_MAX_SECONDS = 600.0
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_RETRY_AFTER = 60.0
DEFAULT_MAX_CATEGORY_PAGES = 2
DEFAULT_MAX_CATEGORY_SEEDS = 3

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
]
