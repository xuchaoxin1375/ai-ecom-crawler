"""Scrapy settings for the bounded skatepro.es trial."""

BOT_NAME = "skatepro"

SPIDER_MODULES = ["skatepro.spiders"]
NEWSPIDER_MODULE = "skatepro.spiders"

USER_AGENT = (
    "fc-scrapy-skatepro/0.1 "
    "(framework-comparison experiment; respects robots.txt; contact: local)"
)

# The storefront serves its public pages with a Spanish Accept-Language header;
# the first attempt without it received HTTP 403 for /sitemap.xml and the same
# URL answered 200 to a request that carried it.  Keep the browser-equivalent
# negotiation headers explicit and fixed.
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

# robots.txt declares Crawl-delay: 10 for this host; the experiment also fixes
# concurrency at 1.
ROBOTSTXT_OBEY = True
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 10.0
DOWNLOAD_DELAY_JITTER = 0
RANDOMIZE_DOWNLOAD_DELAY = False

# 429 is handled by the spider so Retry-After is respected; the built-in retry
# only covers server-side transient errors.
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524]
RETRY_PRIORITY_ADJUST = -1

DOWNLOAD_TIMEOUT = 60
DNS_TIMEOUT = 30
REDIRECT_ENABLED = True
REDIRECT_MAX_TIMES = 3
COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False
AUTOTHROTTLE_ENABLED = False

HTTPERROR_ALLOW_ALL = True
LOG_LEVEL = "INFO"
LOGSTATS_INTERVAL = 30
FEED_EXPORT_ENCODING = "utf-8"

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

ITEM_PIPELINES = {
    "skatepro.pipelines.ResultWriterPipeline": 300,
}

# Populated by run.py for each execution.
MAX_PRODUCTS = 30
MAX_SECONDS = 600
OUTPUT_DIR = "."
RESULTS_DIR = ""
TASK_ID = ""
