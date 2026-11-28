"""Contract constants and normalized product model for D02.

Business rules live in ``docs/02`` and ``docs/09``.  This module only carries
the machine-readable projection used by the export pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

DESCRIPTION_STATUSES = (
    "COMPLETE",
    "PARTIAL",
    "SUMMARY_FALLBACK",
    "NOT_PROVIDED",
    "FAILED",
)

OPTIONAL_QUALITY_FIELDS = frozenset(
    {
        "brand",
        "category",
        "categories",
        "availability",
        "options",
        "sales_unit",
    }
)

TASK_STATES = (
    "DRAFT",
    "QUEUED",
    "RUNNING",
    "PAUSING",
    "PAUSED",
    "CANCELLING",
    "CANCELLED",
    "FINISHED",
)

OUTCOMES = ("COMPLETED", "PARTIAL", "FAILED", "CANCELLED")

STOP_REASONS = (
    "NATURAL_END",
    "BUDGET_EXHAUSTED",
    "ACCESS_DENIED",
    "LANGUAGE_MISMATCH",
    "QUALITY_BLOCKED",
    "ENVIRONMENT_ERROR",
    "PLAN_ERROR",
    "USER_CANCELLED",
    "OTHER",
)

TASK_TYPES = ("product", "discovery")

COVERAGE_STATUSES = ("KNOWN", "PARTIAL", "UNKNOWN")

BUSINESS_ACCEPTANCE_STATUSES = (
    "NOT_REVIEWED",
    "ACCEPTED_BY_USER",
    "REJECTED_BY_USER",
)

CSV_COLUMNS = (
    "name",
    "price_amount",
    "price_currency",
    "primary_image_url",
    "description_html",
    "category",
    "brand",
    "attributes",
    "source_url",
)

# Price-related outcomes are business exclusions, not technical failures.
EXCLUDED_REASONS = frozenset(
    {
        "MISSING_PRICE",
        "NON_POSITIVE_PRICE",
        "INVALID_PRICE",
        "AMBIGUOUS_PRICE",
        "DUPLICATE_SOURCE_URL",
        "MARKET_MISMATCH",
    }
)


class ContractError(ValueError):
    """A task, run directory or output violates the published contract."""


class RecordIssue(ValueError):
    """A candidate cannot become a valid product.

    ``code`` is a stable diagnostic reason.  The pipeline maps price-related
    codes to the excluded stream and every other code to the failed stream.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail or code
        super().__init__(self.detail)


@dataclass(frozen=True)
class OptionGroup:
    """One public purchase option dimension."""

    name: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class NormalizedProduct:
    """Internal normalized record; the 9-column CSV is a projection of it."""

    name: str
    price_amount: Decimal
    price_currency: str
    primary_image_url: str
    description_html: str
    description_status: str
    partial_reason: str | None
    missing_reasons: dict[str, str]
    categories: tuple[str, ...]
    category: str
    brand: str | None
    options: tuple[OptionGroup, ...]
    attributes: str
    source_url: str
    market: str
    locale: str
    availability: str | None
    availability_observed: str | None
    sales_unit: str | None
    tax_basis: str
    price_basis: str
    extracted_at: str | None
    price_displayed: Decimal | None = None
    price_pretax: Decimal | None = None
    relations: tuple[dict[str, str], ...] = ()
    variants: tuple[dict[str, Any], ...] = ()
    field_sources: dict[str, str] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """Serialize the internal record (not the 9-column business CSV)."""
        return {
            "name": self.name,
            "price": {
                "amount": float(self.price_amount),
                "currency": self.price_currency,
                "basis": self.price_basis,
                "tax_basis": self.tax_basis,
                "displayed": None
                if self.price_displayed is None
                else float(self.price_displayed),
                "pretax": None if self.price_pretax is None else float(self.price_pretax),
            },
            "primary_image_url": self.primary_image_url,
            "description_html": self.description_html,
            "description_status": self.description_status,
            "partial_reason": self.partial_reason,
            "missing_reasons": dict(self.missing_reasons),
            "categories": list(self.categories),
            "category": self.category,
            "brand": self.brand,
            "options": [
                {"name": group.name, "values": list(group.values)}
                for group in self.options
            ],
            "attributes": self.attributes,
            "source_url": self.source_url,
            "market": self.market,
            "locale": self.locale,
            "availability": self.availability,
            "availability_observed": self.availability_observed,
            "sales_unit": self.sales_unit,
            "relations": [dict(item) for item in self.relations],
            "variants": [dict(item) for item in self.variants],
            "extracted_at": self.extracted_at,
            "field_sources": dict(self.field_sources),
        }

    def quality_exception(self) -> dict[str, Any] | None:
        """Return the docs/09 exception entry, or ``None`` for a clean record.

        Optional business fields (brand, category, availability, options and
        sales unit) may be absent without turning the product into a quality
        exception.  They remain in the internal record's ``missing_reasons``;
        only description quality and non-optional missing reasons are surfaced
        in the task report.
        """
        quality_missing = {
            key: value
            for key, value in self.missing_reasons.items()
            if key not in OPTIONAL_QUALITY_FIELDS
        }
        status = str(self.description_status or "").upper()
        if status == "COMPLETE" and not quality_missing:
            return None
        return {
            "source_url": self.source_url,
            "description_status": self.description_status,
            "partial_reason": self.partial_reason,
            "missing_reasons": quality_missing,
        }


@dataclass(frozen=True)
class ExportResult:
    """In-memory result of one export pass."""

    products: tuple[NormalizedProduct, ...]
    excluded: tuple[dict[str, Any], ...]
    failed: tuple[dict[str, Any], ...]
    task_result: dict[str, Any]
