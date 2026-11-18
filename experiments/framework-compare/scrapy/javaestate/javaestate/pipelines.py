"""Writes the contract-shaped outputs after the bounded crawl."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from scrapy import Spider

from javaestate.normalize import CSV_FIELDS, csv_safe


class ResultWriterPipeline:
    def __init__(self) -> None:
        self.crawler = None
        self.valid: list[dict[str, str]] = []
        self.excluded: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []
        self.seen_valid: set[str] = set()
        self.output_dir = Path(".")

    @classmethod
    def from_crawler(cls, crawler) -> "ResultWriterPipeline":
        pipeline = cls()
        pipeline.crawler = crawler
        return pipeline

    @property
    def spider(self) -> Spider:
        if self.crawler is None or self.crawler.spider is None:
            raise RuntimeError("pipeline has no spider")
        return self.crawler.spider

    def open_spider(self) -> None:
        spider = self.spider
        self.output_dir = Path(spider.settings.get("OUTPUT_DIR") or ".")
        (self.output_dir / "diagnostics").mkdir(parents=True, exist_ok=True)

    def process_item(self, item: dict[str, Any]) -> dict[str, Any]:
        spider = self.spider
        kind = item.get("_kind")
        if kind == "valid":
            row = item["row"]
            source_url = row.get("source_url", "")
            if source_url in self.seen_valid:
                spider.logger.warning("duplicate valid item ignored: %s", source_url)
                return item
            self.seen_valid.add(source_url)
            self.valid.append(row)
        elif kind == "excluded":
            self.excluded.append(item["record"])
        elif kind == "failed":
            self.failed.append(item["record"])
        else:
            spider.logger.error("unknown item kind: %r", kind)
        return item

    def close_spider(self) -> None:
        spider = self.spider
        output_dir = self.output_dir
        diagnostics = output_dir / "diagnostics"
        diagnostics.mkdir(parents=True, exist_ok=True)

        self.write_valid_csv(output_dir / "valid.csv")
        self.write_records(
            diagnostics / "excluded_products.csv",
            self.excluded,
            ["source_url", "handle", "name", "price_amount", "reason", "details", "extracted_at"],
        )
        self.write_records(
            diagnostics / "failed_products.csv",
            self.failed,
            ["source_url", "handle", "stage", "reason", "details", "extracted_at"],
        )

        processed_urls = set(spider.processed_urls)
        pending_selected = [
            candidate for candidate in spider.selected if candidate["url"] not in processed_urls
        ]
        pending_rows = [
            {
                "source_url": candidate["url"],
                "handle": candidate["handle"],
                "reason": "not_processed_before_stop",
            }
            for candidate in pending_selected
        ]
        self.write_records(
            diagnostics / "pending_products.csv",
            pending_rows,
            ["source_url", "handle", "reason"],
        )

        task_result = spider.task_result()
        self.write_json(output_dir / "task-result.json", task_result)

        meta = spider.run_meta()
        meta["pending_selected"] = pending_selected
        meta["out_of_sample_pending"] = max(
            0, (spider.denominator or 0) - task_result["counts"]["processed_products"]
        )
        self.write_json(diagnostics / "run-meta.json", meta)

        self.write_events(diagnostics / "events.json", spider.events)
        spider.logger.info(
            "outputs written: valid=%s excluded=%s failed=%s pending_selected=%s",
            len(self.valid),
            len(self.excluded),
            len(self.failed),
            len(pending_selected),
        )

    def write_valid_csv(self, path: Path) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=CSV_FIELDS,
                quoting=csv.QUOTE_MINIMAL,
                lineterminator="\r\n",
            )
            writer.writeheader()
            for row in self.valid:
                writer.writerow({field: csv_safe(row.get(field, "")) for field in CSV_FIELDS})

    def write_records(self, path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=fields,
                quoting=csv.QUOTE_MINIMAL,
                lineterminator="\r\n",
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({field: csv_safe(row.get(field, "")) for field in fields})

    def write_json(self, path: Path, payload: Any) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def write_events(self, path: Path, events: list[dict[str, Any]]) -> None:
        self.write_json(path, {"events": events})
