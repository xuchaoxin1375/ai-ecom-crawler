"""Scrapy settings for the bounded javaestate.com trial."""

BOT_NAME = "javaestate"
SPIDER_MODULES = ["javaestate.spiders"]
NEWSPIDER_MODULE = "javaestate.spiders"

USER_AGENT = (
    "fc-scrapy-javaestate/0.1 "
    "(framework-comparison experiment; respects robots.txt; contact: local)"
)

ROBOTSTXT_OBEY = True

# The experiment fixes concurrency at 1 and a request interval >= 1 s.
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 2.0
DOWNLOAD_DELAY_JITTER = 0

# A bounded, polite backoff.  429 is handled by the spider so Retry-After is
# respected; the built-in retry only covers server-side transient errors.
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

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2.0
AUTOTHROTTLE_MAX_DELAY = 90.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 0.5
AUTOTHROTTLE_DEBUG = False

HTTPERROR_ALLOW_ALL = True
LOG_LEVEL = "INFO"
LOGSTATS_INTERVAL = 30
FEED_EXPORT_ENCODING = "utf-8"

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

ITEM_PIPELINES = {
    "javaestate.pipelines.ResultWriterPipeline": 300,
}

# Populated by run.py for each execution.
MAX_PRODUCTS = 30
MAX_SECONDS = 600
OUTPUT_DIR = "."
RESULTS_DIR = ""
TASK_ID = ""
BUILD_STARTED_AT = ""
PLAN_CREATED_AT = ""
PLAN_REVISIONS = 0
RUNTIME_LLM_CALLS = 0
