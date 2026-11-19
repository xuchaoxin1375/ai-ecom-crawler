"""Fixed configuration for the skatepro.es Crawlee plan."""

from __future__ import annotations

SITE_HOST = "www.skatepro.es"
SITE_ORIGIN = "https://www.skatepro.es"
SITEMAP_URLS = ["https://www.skatepro.es/sitemap.xml"]
ROBOTS_URL = "https://www.skatepro.es/robots.txt"

# Public product pages look like /<category>-<product>.htm and are the only
# paths enqueued as products.  Category pages (/c*.htm), brand pages (/m*.htm)
# and informational pages are discovery-only and never fetched by this plan.
PRODUCT_URL_RE = r"^https://www\.skatepro\.es/\d+-\d+\.htm$"

PLAN_ID = "skatepro-es-es-es-eur"
PLAN_VERSION = "2026.11.19-2"
SCHEMA_VERSION = "1.0"

MARKET = "ES"
LOCALE = "es-ES"
CURRENCY = "EUR"

MAX_PRODUCTS = 30
TIME_BUDGET_SECONDS = 600
# robots.txt publishes "Crawl-delay: 10" for automated agents; the plan uses
# one request every 10 seconds instead of the 1 second experiment floor.
MIN_REQUEST_INTERVAL_SECONDS = 10.0
MAX_REQUEST_RETRIES = 2  # three attempts in total, below the three-retry ceiling
MAX_429_STALL_SECONDS = 190  # three 60-second Retry-After windows
NAVIGATION_TIMEOUT_MS = 30_000

# Each fix/re-run uses a new task id and a new plan_version; old results keep
# their original plan_version.
DEFAULT_TASK_ID = "fc-crawlee-skatepro"
