"""Fixed configuration for the javaestate.com Crawlee plan."""

from __future__ import annotations

SITE_ORIGIN = "https://javaestate.com"
SITEMAP_INDEX_URL = "https://javaestate.com/sitemap.xml"
PRODUCT_URL_PREFIX = "/products/"
ROBOTS_URL = "https://javaestate.com/robots.txt"

PLAN_ID = "javaestate-us-en-usd"
PLAN_VERSION = "2026.11.19-2"
SCHEMA_VERSION = "1.0"

MARKET = "US"
LOCALE = "en-US"
CURRENCY = "USD"

MAX_PRODUCTS = 30
TIME_BUDGET_SECONDS = 600
MIN_REQUEST_INTERVAL_SECONDS = 1.1
MAX_REQUEST_RETRIES = 2  # three attempts in total, never more than three retries
MAX_429_STALL_SECONDS = 190  # three 60-second Retry-After windows
NAVIGATION_TIMEOUT_MS = 45_000

# The first run of this plan.  Each fix/re-run uses a new value and a new
# plan_version; old results keep their original plan_version.
DEFAULT_TASK_ID = "fc-crawlee-javaestate"
