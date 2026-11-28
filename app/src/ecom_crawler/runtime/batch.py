"""Site import parsing shared by the batch API and tests.

The parser keeps the original input for audit, while ``site_key`` is the
normalized domain used for deduplication and rule matching.  Invalid and
duplicate rows are returned as explicit items instead of being dropped, so the
import preview can explain every skipped line.
"""

from __future__ import annotations

import csv
import io
import ipaddress
import re
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from .rule import RulePackage

_HEADER_CELLS = {"url", "site", "domain", "website", "网址", "站点", "域名"}
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
BATCH_COLLECTION_LIMITS = {
    "sample": {"max_urls": 100, "max_products": 20, "max_seconds": 180},
    # Formal collection defaults to the rule's declared catalog and natural
    # end: no service-level product, URL or duration cap.  Operators can still
    # send explicit limits for a bounded formal run.
    "formal": {"max_urls": None, "max_products": None, "max_seconds": None},
}


@dataclass(frozen=True)
class ParsedSite:
    input_value: str
    domain: str
    site_key: str | None
    error: str | None = None
    duplicate_of: str | None = None

    @property
    def valid(self) -> bool:
        return self.error is None and self.duplicate_of is None


def parse_site_text(text: str) -> list[str]:
    """Split pasted text or a CSV first column into raw site entries."""
    values: list[str] = []
    for index, line in enumerate(text.splitlines()):
        entry = line.strip().lstrip("\ufeff")
        if not entry:
            continue
        if "," in entry:
            try:
                entry = next(csv.reader(io.StringIO(entry)))[0].strip()
            except (StopIteration, csv.Error):
                entry = entry.split(",", 1)[0].strip()
        if index == 0 and entry.lower() in _HEADER_CELLS:
            continue
        if entry:
            values.append(entry)
    return values


def normalize_site(raw: str) -> ParsedSite:
    """Normalize one URL or domain; return a reason instead of raising."""
    value = raw.strip().lstrip("\ufeff")
    if not value:
        return ParsedSite(raw, raw, None, error="空行")
    if any(character.isspace() for character in value):
        return ParsedSite(value, value, None, error="网址包含空白字符")

    candidate = value if "://" in value else f"https://{value}"
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ParsedSite(value, value, None, error="网址格式无效")

    if parsed.scheme.lower() not in {"http", "https"}:
        return ParsedSite(value, value, None, error="仅支持 http/https 网址")
    if parsed.username or parsed.password:
        return ParsedSite(value, value, None, error="网址不能包含账号或密码")

    hostname = (parsed.hostname or "").strip().rstrip(".").lower()
    if not hostname:
        return ParsedSite(value, value, None, error="网址不完整，缺少域名")
    if len(hostname) > 253:
        return ParsedSite(value, value, None, error="域名过长")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        return ParsedSite(value, value, None, error="请提交站点域名，不是 IP 地址")

    try:
        ascii_domain = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return ParsedSite(value, hostname, None, error="域名包含无效字符")
    ascii_domain = ascii_domain.rstrip(".").lower()
    labels = ascii_domain.split(".")
    if len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        return ParsedSite(value, hostname, None, error="域名不完整或包含无效字符")

    site_key = ascii_domain.removeprefix("www.")
    if "." not in site_key:
        return ParsedSite(value, hostname, None, error="域名不完整")
    return ParsedSite(value, hostname, site_key)


def target_entry(value: str) -> str | None:
    parts = urlsplit(value if "://" in value else f"https://{value}")
    path = parts.path or "/"
    if path == "/" and not parts.query:
        return None
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def target_key(domain: str, entry: str | None, market: str | None) -> str:
    normalized_market = (market or "").strip().upper()
    if entry is None and not normalized_market:
        return domain
    digest = sha256(f"{entry or ''}\n{normalized_market}".encode()).hexdigest()[:16]
    return f"{domain}--{digest}"


def site_identity(
    domain: str, value: str, market: str | None
) -> tuple[str, str | None, str]:
    """Return the cross-batch identity used by workbench pending targets.

    ``site_key`` is not stable across scoped and unscoped batches, so pending
    target comparisons use domain, target entry and market instead.
    """
    parsed = normalize_site(value)
    host = parsed.site_key or normalize_site(domain).site_key
    if not host:
        host = str(domain).strip().lower().removeprefix("www.")
    return host, target_entry(value), (market or "").strip().upper()


def rule_has_catalog_discovery(rule: RulePackage) -> bool:
    return bool(rule.product_source) or any(
        source.get("type") in {"listing", "sitemap", "html_index", "public_json"}
        for source in rule.sources
    )


def target_entry_mode(rule: RulePackage, entry: str | None) -> str | None:
    if entry is None:
        return "catalog"
    sources = rule.sources
    exact_sources = (
        not rule.product_source
        and bool(sources)
        and all(
            source.get("type") in {"entry_links", "listing", "html_index"}
            and target_entry(str(source.get("url") or source.get("seed") or rule.entry_url))
            == entry
            for source in sources
        )
    )
    if exact_sources and any(source.get("type") != "entry_links" for source in sources):
        return "catalog"

    url = urlsplit(entry)
    origin = f"{url.scheme.lower()}://{url.netloc.lower()}"
    if (
        url.scheme in {"http", "https"}
        and origin in {allowed.rstrip("/") for allowed in rule.site["allowed_origins"]}
        and any(url.path.startswith(prefix) for prefix in rule.site["allowed_path_prefixes"])
        and all(not re.search(pattern, entry) for pattern in rule.scope.get("exclude", []))
        and (
            not rule.scope.get("include")
            or any(re.search(pattern, url.path) for pattern in rule.scope["include"])
        )
        and any(re.search(pattern, url.path) for pattern in rule.discovery["product_url_patterns"])
    ):
        return "product"
    return "catalog" if exact_sources else None


def within_target_navigation(url: str, entry: str, *, page_param: str | None = None) -> bool:
    target = urlsplit(entry)
    actual = urlsplit(url)
    path = target.path.rstrip("/")
    target_query = {(key, value) for key, value in parse_qsl(target.query, keep_blank_values=True) if key != page_param}
    filter_keys = {key for key, _ in target_query}
    actual_query = {(key, value) for key, value in parse_qsl(actual.query, keep_blank_values=True) if key in filter_keys}
    return (
        actual.scheme == target.scheme
        and actual.netloc.lower() == target.netloc.lower()
        and (actual.path.rstrip("/") == path or actual.path.startswith(f"{path}/"))
        and target_query == actual_query
    )


def parse_sites(
    values: list[str], *, scoped: bool = False, market: str | None = None
) -> list[ParsedSite]:
    """Normalize entries in order and mark duplicates after the first one.

    A duplicate is reported against the first input that produced the same
    normalized key, matching the preview rule that only the first row is kept.
    """
    parsed: list[ParsedSite] = []
    first_seen: dict[str, str] = {}
    for raw in values:
        item = normalize_site(raw)
        if item.site_key is not None:
            if scoped:
                item = ParsedSite(
                    item.input_value, item.domain,
                    target_key(item.site_key, target_entry(item.input_value), market),
                )
            previous = first_seen.get(item.site_key)
            if previous is not None:
                item = ParsedSite(
                    item.input_value,
                    item.domain,
                    item.site_key,
                    duplicate_of=previous,
                )
            else:
                first_seen[item.site_key] = item.input_value
        parsed.append(item)
    return parsed


def rule_domains(site: dict[str, str] | None) -> set[str]:
    """Extract normalized domain keys from a rule package's site block."""
    if not isinstance(site, dict):
        return set()
    origins = list(site.get("entry_urls") or [])
    origins.extend(site.get("allowed_origins") or [])
    domains: set[str] = set()
    for origin in origins:
        if not isinstance(origin, str):
            continue
        parsed = normalize_site(origin)
        if parsed.site_key:
            domains.add(parsed.site_key)
    return domains
