#!/usr/bin/env python3
"""check_examples.py - 校验 docs/示例 与 02／09 契约的一致性。

用法:
    python scripts/check_examples.py
    python scripts/check_examples.py --examples-dir docs/示例 --verbose
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXAMPLES = REPO_ROOT / "docs" / "示例"
EXPECTED_COLUMNS = [
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
REQUIRED_PRODUCT_FIELDS = [
    "name",
    "price",
    "primary_image_url",
    "description_html",
    "description_format",
    "categories",
    "brand",
    "options",
    "source_url",
    "market",
    "locale",
    "availability",
    "price_basis",
    "tax_basis",
    "description_status",
    "partial_reason",
    "missing_reasons",
    "task_id",
    "plan_id",
    "plan_version",
    "extracted_at",
]
REQUIRED_TASK_FIELDS = [
    "task_id",
    "plan_id",
    "plan_version",
    "market",
    "locale",
    "state",
    "outcome",
    "stop_reason",
    "counts",
    "coverage",
    "business_acceptance",
]
REQUIRED_COUNTS = [
    "discovered_urls",
    "pending_navigation_entries",
    "product_candidates",
    "pending_products",
    "in_flight_products",
    "processed_products",
    "valid_products",
    "excluded_products",
    "failed_products",
    "partial_description_products",
]

logger = logging.getLogger("check_examples")


class ExampleError(ValueError):
    """示例与契约不一致。"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="校验 docs/示例 的 CSV、商品记录、排除记录和任务结果是否与 02／09 契约一致。",
    )
    parser.add_argument(
        "--examples-dir",
        default=str(DEFAULT_EXAMPLES),
        help=f"示例目录，默认 {DEFAULT_EXAMPLES}",
    )
    parser.add_argument("--verbose", action="store_true", help="输出逐项检查细节")
    return parser.parse_args(argv)


def read_json(path: Path) -> Any:
    """读取 UTF-8 JSON。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExampleError(f"缺少文件: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExampleError(f"JSON 无法解析: {path}: {exc}") from exc


def require(condition: bool, message: str) -> None:
    """条件不成立时抛出校验错误。"""
    if not condition:
        raise ExampleError(message)


def serialize_options(options: list[dict[str, Any]]) -> str:
    """按 02 的兼容属性串规则序列化 options。"""

    def escape(value: str) -> str:
        return (
            value.replace("\\", "\\\\").replace("#", "\\#").replace("|", "\\|").replace("~", "\\~")
        )

    parts: list[str] = []
    for option in options:
        name = escape(str(option["name"]))
        values = "|".join(escape(str(value)) for value in option["values"])
        parts.append(f"{name}#{values}")
    return "~".join(parts)


def read_products(path: Path) -> list[dict[str, Any]]:
    """读取并校验商品记录。"""
    products = read_json(path)
    require(isinstance(products, list) and len(products) == 2, "商品记录应为 2 条")
    for index, product in enumerate(products, start=1):
        require(isinstance(product, dict), f"商品记录第 {index} 条不是对象")
        missing = [field for field in REQUIRED_PRODUCT_FIELDS if field not in product]
        require(not missing, f"商品记录第 {index} 条缺少字段: {', '.join(missing)}")
        price = product["price"]
        require(isinstance(price, dict), f"商品记录第 {index} 条 price 不是对象")
        amount = price.get("amount")
        require(
            isinstance(amount, (int, float)) and amount > 0,
            f"商品记录第 {index} 条 price.amount 不是正数",
        )
        currency = price.get("currency")
        require(
            isinstance(currency, str) and len(currency) == 3 and currency.isupper(),
            f"商品记录第 {index} 条 price.currency 不是三字母大写币种",
        )
        require(
            product["description_status"] in {"COMPLETE", "PARTIAL"},
            f"商品记录第 {index} 条 description_status 非法",
        )
        if product["description_status"] == "PARTIAL":
            require(
                isinstance(product["partial_reason"], str) and bool(product["partial_reason"]),
                f"商品记录第 {index} 条 PARTIAL 缺少 partial_reason",
            )
        else:
            require(
                product["partial_reason"] is None,
                f"商品记录第 {index} 条 COMPLETE 不应有 partial_reason",
            )
        require(
            isinstance(product["missing_reasons"], dict),
            f"商品记录第 {index} 条 missing_reasons 不是对象",
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("商品记录 %s: %s", index, product["source_url"])
    return products


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """读取并校验 9 列业务 CSV。"""
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = [str(name) for name in reader.fieldnames or []]
            require(header == EXPECTED_COLUMNS, f"CSV 列顺序不正确: {header}")
            rows = [dict(row) for row in reader]
    except FileNotFoundError as exc:
        raise ExampleError(f"缺少文件: {path}") from exc
    require(len(rows) == 2, f"商品 CSV 应为 2 行，实际 {len(rows)} 行")
    for index, row in enumerate(rows, start=1):
        require(all(value is not None for value in row.values()), f"CSV 第 {index} 行字段数不足")
        amount = row["price_amount"]
        try:
            require(float(amount) > 0, f"CSV 第 {index} 行 price_amount 不是正数")
        except ValueError as exc:
            raise ExampleError(f"CSV 第 {index} 行 price_amount 不是数值: {amount}") from exc
        require(
            len(row["price_currency"]) == 3 and row["price_currency"].isupper(),
            f"CSV 第 {index} 行 price_currency 非法",
        )
        require(
            row["source_url"].startswith("https://shop.example/"),
            f"CSV 第 {index} 行 source_url 不是合成示例域名",
        )
    return header, cast(list[dict[str, str]], rows)


def check_products_against_csv(products: list[dict[str, Any]], rows: list[dict[str, str]]) -> None:
    """逐条核对内部商品记录与 9 列 CSV。"""
    for index, (product, row) in enumerate(zip(products, rows, strict=True), start=1):
        require(row["name"] == product["name"], f"第 {index} 行 name 不一致")
        require(
            float(row["price_amount"]) == float(product["price"]["amount"]),
            f"第 {index} 行 price_amount 不一致",
        )
        require(
            row["price_currency"] == product["price"]["currency"],
            f"第 {index} 行 price_currency 不一致",
        )
        require(
            row["primary_image_url"] == product["primary_image_url"],
            f"第 {index} 行 primary_image_url 不一致",
        )
        require(
            row["description_html"] == product["description_html"],
            f"第 {index} 行 description_html 不一致",
        )
        expected_category = product["categories"][0] if product["categories"] else ""
        require(row["category"] == expected_category, f"第 {index} 行 category 不一致")
        require(row["brand"] == (product["brand"] or ""), f"第 {index} 行 brand 不一致")
        require(
            row["attributes"] == serialize_options(product["options"]),
            f"第 {index} 行 attributes 序列化不一致",
        )
        require(row["source_url"] == product["source_url"], f"第 {index} 行 source_url 不一致")


def check_task_result(
    path: Path,
    products: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    csv_count: int,
) -> None:
    """校验任务结果字段、计数不变量和质量例外。"""
    result = read_json(path)
    require(isinstance(result, dict), "任务结果不是对象")
    missing = [field for field in REQUIRED_TASK_FIELDS if field not in result]
    require(not missing, f"任务结果缺少字段: {', '.join(missing)}")

    counts = result["counts"]
    require(isinstance(counts, dict), "任务结果 counts 不是对象")
    missing_counts = [field for field in REQUIRED_COUNTS if field not in counts]
    require(not missing_counts, f"任务结果 counts 缺少字段: {', '.join(missing_counts)}")
    require(
        counts["product_candidates"]
        == counts["pending_products"] + counts["in_flight_products"] + counts["processed_products"],
        "计数不变量失败: product_candidates",
    )
    require(
        counts["processed_products"]
        == counts["valid_products"] + counts["excluded_products"] + counts["failed_products"],
        "计数不变量失败: processed_products",
    )
    require(
        counts["partial_description_products"] <= counts["valid_products"],
        "计数不变量失败: partial_description_products",
    )
    require(
        result["state"] not in {"PAUSED", "CANCELLED", "FINISHED"}
        or counts["in_flight_products"] == 0,
        "终态任务的 in_flight_products 应为 0",
    )
    require(counts["valid_products"] == csv_count, "valid_products 与 CSV 行数不一致")
    require(
        counts["valid_products"] == len(products),
        "valid_products 与商品记录数不一致",
    )
    require(
        counts["excluded_products"] == len(excluded),
        "excluded_products 与排除记录数不一致",
    )
    require(
        counts["product_candidates"] == len(products) + len(excluded),
        "product_candidates 与商品／排除记录总数不一致",
    )

    coverage = result["coverage"]
    require(isinstance(coverage, dict), "coverage 不是对象")
    require(
        coverage.get("status") in {"KNOWN", "PARTIAL", "UNKNOWN"},
        "coverage.status 非法",
    )
    if coverage.get("status") == "UNKNOWN":
        require(coverage.get("denominator") is None, "UNKNOWN 覆盖不应有 denominator")

    acceptance = result["business_acceptance"]
    require(isinstance(acceptance, dict), "business_acceptance 不是对象")
    require(
        isinstance(acceptance.get("status"), str) and acceptance["status"],
        "business_acceptance.status 为空",
    )
    require(
        isinstance(result["stop_reason"], str) and bool(result["stop_reason"]),
        "stop_reason 为空",
    )

    partial_products = {
        product["source_url"]
        for product in products
        if product["description_status"] == "PARTIAL" and isinstance(product["source_url"], str)
    }
    exceptions = result.get("quality_exceptions", [])
    require(isinstance(exceptions, list), "quality_exceptions 不是数组")
    exception_urls = {
        item["source_url"]
        for item in exceptions
        if isinstance(item, dict) and isinstance(item.get("source_url"), str)
    }
    require(
        partial_products == exception_urls,
        "quality_exceptions 与 PARTIAL 商品不一致: "
        f"expected={sorted(partial_products)}, actual={sorted(exception_urls)}",
    )


def check_examples(examples_dir: Path) -> None:
    """执行全部示例一致性检查。"""
    require(examples_dir.is_dir(), f"示例目录不存在: {examples_dir}")
    products = read_products(examples_dir / "商品记录.json")
    _, rows = read_csv_rows(examples_dir / "商品导出.csv")
    check_products_against_csv(products, rows)

    excluded = read_json(examples_dir / "排除记录.json")
    require(isinstance(excluded, list) and len(excluded) == 1, "排除记录应为 1 条")
    require(isinstance(excluded[0], dict), "排除记录第 1 条不是对象")
    require(
        excluded[0].get("included_in_valid_export") is False,
        "排除记录不应进入有效导出",
    )
    require(
        excluded[0].get("reason") == "NON_POSITIVE_PRICE",
        "排除记录原因应为 NON_POSITIVE_PRICE",
    )

    check_task_result(
        examples_dir / "任务结果.json",
        products,
        excluded,
        len(rows),
    )


def main() -> int:
    """入口函数：返回进程退出码。"""
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    examples_dir = Path(args.examples_dir)
    try:
        check_examples(examples_dir)
    except ExampleError as exc:
        logger.error("示例校验失败: %s", exc)
        return 1
    logger.info("通过: %s", examples_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
