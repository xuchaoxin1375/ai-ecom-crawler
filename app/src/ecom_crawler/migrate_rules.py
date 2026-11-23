"""One-shot migration for the v2 rule-version ledger.

The runtime keeps creating new tables and columns lazily.  This command scans
an existing database and the rules directory once, backfills the rule ledger,
site pointers, task hashes and build target versions, and writes a report.
It refuses to overwrite an existing ``site_rules`` pointer or an existing
``rule_versions`` row.

Usage::

    python -m ecom_crawler.migrate_rules --db tasks.db --rules-dir rules

Run it while the web service and worker are stopped.  Repeat runs are safe:
already migrated rows are skipped and a new report is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .runtime.store import TaskStore

REPORT_LIMIT = 500


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_rule_path(rules_dir: Path, raw: Any) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        return None
    resolved = (rules_dir / candidate).resolve()
    try:
        resolved.relative_to(rules_dir.resolve())
    except ValueError:
        return None
    return resolved


def _read_rule(path: Path) -> dict[str, Any] | None:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return payload if isinstance(payload, dict) else None


def _created_at(payload: dict[str, Any], path: Path) -> str:
    value = str(payload.get("updated_at") or "").strip()
    if value:
        return value
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat().replace(
        "+00:00", "Z"
    )


def _append_missing(
    report: dict[str, Any],
    source: str,
    record_id: str,
    raw_path: Any,
    rules_dir: Path | None = None,
) -> None:
    item = {
        "source": source,
        "id": record_id,
        "path": _report_path(raw_path, rules_dir),
    }
    if item not in report["missing_rule_files"] and len(
        report["missing_rule_files"]
    ) < REPORT_LIMIT:
        report["missing_rule_files"].append(item)


def _report_path(raw: Any, rules_dir: Path | None = None) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    path = Path(text)
    if rules_dir is not None and path.is_absolute():
        try:
            return path.resolve().relative_to(rules_dir.resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def _scan_rule_files(
    rules_dir: Path, report: dict[str, Any]
) -> tuple[
    dict[tuple[str, str], list[dict[str, Any]]],
    dict[str, str],
]:
    versions: dict[tuple[str, str], list[dict[str, Any]]] = {}
    hashes: dict[str, str] = {}
    paths = sorted(
        {
            *rules_dir.rglob("*.yaml"),
            *rules_dir.rglob("*.yml"),
        }
    )
    for path in paths:
        if not path.is_file() or path.name.endswith(".tmp"):
            continue
        report["counts"]["rule_files_scanned"] += 1
        payload = _read_rule(path)
        if payload is None:
            report["invalid_rule_files"].append({"path": path.name})
            continue
        rule_id = str(payload.get("rule_id") or "").strip()
        rule_version = str(payload.get("rule_version") or "").strip()
        if not rule_id or not rule_version:
            report["invalid_rule_files"].append(
                {"path": path.name, "reason": "missing rule_id or rule_version"}
            )
            continue
        try:
            digest = sha256_file(path)
        except OSError:
            report["invalid_rule_files"].append(
                {"path": path.name, "reason": "unreadable"}
            )
            continue
        hashes[str(path)] = digest
        versions.setdefault((rule_id, rule_version), []).append(
            {
                "sha256": digest,
                "path": path,
                "relative": path.relative_to(rules_dir).as_posix(),
                "payload": payload,
            }
        )
    return versions, hashes


def _select_versions(
    versions: dict[tuple[str, str], list[dict[str, Any]]], report: dict[str, Any]
) -> dict[tuple[str, str], dict[str, Any]]:
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for key, items in sorted(versions.items()):
        by_hash: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_hash.setdefault(str(item["sha256"]), []).append(item)
        if len(by_hash) > 1:
            report["rule_version_conflicts"].append(
                {
                    "rule_id": key[0],
                    "rule_version": key[1],
                    "hashes": sorted(by_hash),
                    "paths": sorted(
                        item["relative"] for item in items
                    ),
                }
            )
            continue
        chosen = min(by_hash[next(iter(by_hash))], key=lambda item: item["path"].name)
        selected[key] = chosen
    return selected


def _migrate_site_rules(
    connection: sqlite3.Connection,
    rules_dir: Path,
    hashes: dict[str, str],
    selected: dict[tuple[str, str], dict[str, Any]],
    report: dict[str, Any],
    dry_run: bool,
) -> dict[tuple[str, str], str]:
    """Backfill site pointers and return activation timestamps per version."""

    rows = connection.execute(
        """
        SELECT site_key, rule_id, rule_version, rule_path, updated_at
        FROM batch_sites
        WHERE rule_id IS NOT NULL AND rule_version IS NOT NULL
        ORDER BY site_key, updated_at DESC
        """
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        report["counts"]["batch_sites_scanned"] += 1
        grouped.setdefault(row["site_key"], []).append(row)

    existing = {
        row["site_key"]
        for row in connection.execute("SELECT site_key FROM site_rules")
    }
    activated: dict[tuple[str, str], str] = {}
    for site_key, candidates in sorted(grouped.items()):
        report["counts"]["sites_seen"] += 1
        if site_key in existing:
            report["counts"]["site_rules_skipped"] += 1
            continue
        readable: list[tuple[sqlite3.Row, str, str]] = []
        for row in candidates:
            path = _safe_rule_path(rules_dir, row["rule_path"])
            if path is None or not path.is_file():
                _append_missing(
                    report,
                    "batch_site",
                    f"{site_key}:{row['rule_id']}",
                    row["rule_path"],
                    rules_dir,
                )
                continue
            digest = hashes.get(str(path)) or sha256_file(path)
            readable.append((row, digest, str(path)))
        if not readable:
            continue
        chosen, digest, path = readable[0]
        ignored = [
            {
                "rule_id": row["rule_id"],
                "rule_version": row["rule_version"],
                "sha256": row_digest,
            }
            for row, row_digest, _ in readable[1:]
            if (row["rule_id"], row["rule_version"], row_digest)
            != (chosen["rule_id"], chosen["rule_version"], digest)
        ]
        conflicts = {
            (row["rule_id"], row["rule_version"], row_digest)
            for row, row_digest, _ in readable
        }
        if len(conflicts) > 1:
            report["site_rule_conflicts"].append(
                {
                    "site_key": site_key,
                    "chosen": {
                        "rule_id": chosen["rule_id"],
                        "rule_version": chosen["rule_version"],
                        "sha256": digest,
                    },
                    "ignored": ignored,
                }
            )
        if not dry_run:
            connection.execute(
                """
                INSERT INTO site_rules (
                    site_key, rule_id, rule_version, sha256, path, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_key) DO NOTHING
                """,
                (
                    site_key,
                    chosen["rule_id"],
                    chosen["rule_version"],
                    digest,
                    Path(path).resolve().relative_to(rules_dir.resolve()).as_posix(),
                    chosen["updated_at"] or _iso_now(),
                ),
            )
        report["counts"]["site_rules_written"] += 1
        activated[(chosen["rule_id"], chosen["rule_version"])] = (
            chosen["updated_at"] or _iso_now()
        )
        if (chosen["rule_id"], chosen["rule_version"]) not in selected:
            selected[(chosen["rule_id"], chosen["rule_version"])] = {
                "sha256": digest,
                "path": Path(path),
                "relative": Path(path)
                .resolve()
                .relative_to(rules_dir.resolve())
                .as_posix(),
                "payload": _read_rule(Path(path)) or {},
            }
    return activated


def _migrate_rule_versions(
    connection: sqlite3.Connection,
    selected: dict[tuple[str, str], dict[str, Any]],
    activated: dict[tuple[str, str], str],
    report: dict[str, Any],
    dry_run: bool,
) -> None:
    existing = {
        (row["rule_id"], row["rule_version"]): row["sha256"]
        for row in connection.execute(
            "SELECT rule_id, rule_version, sha256 FROM rule_versions"
        )
    }
    active_versions: dict[str, list[str]] = {}
    for rule_id, rule_version in activated:
        active_versions.setdefault(rule_id, []).append(rule_version)
    for key, item in sorted(selected.items()):
        rule_id, rule_version = key
        digest = str(item["sha256"])
        if key in existing:
            if existing[key] != digest:
                report["rule_version_conflicts"].append(
                    {
                        "rule_id": rule_id,
                        "rule_version": rule_version,
                        "hashes": sorted({existing[key], digest}),
                        "paths": [item["path"].name],
                    }
                )
            report["counts"]["rule_versions_skipped"] += 1
            continue
        payload = item["payload"]
        if key in activated:
            status = "active"
        elif (
            str(payload.get("status") or "").strip().lower() == "candidate"
            and rule_version > max(active_versions.get(rule_id, [""]))
        ):
            # A rule file keeps status=candidate after activation.  Only a
            # version newer than every active pointer can still be a pending
            # candidate; older unreferenced files are history, not offers.
            status = "candidate"
        else:
            status = "superseded"
        activated_at = activated.get(key) if status == "active" else None
        if not dry_run:
            connection.execute(
                """
                INSERT INTO rule_versions (
                    rule_id, rule_version, sha256, parent_version, status,
                    source_build_id, source_feedback_id, path, created_at,
                    activated_at, activated_by, reviewed_by, reviewed_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    rule_version,
                    digest,
                    str(payload.get("parent_version") or "") or None,
                    status,
                    None,
                    None,
                    str(item.get("relative") or item["path"].name),
                    _created_at(payload, item["path"]),
                    activated_at,
                    "legacy-migration" if activated_at else None,
                    None,
                    None,
                    "migrated by ecom_crawler.migrate_rules",
                ),
            )
        report["counts"]["rule_versions_written"] += 1


def _task_rule_path(task: sqlite3.Row, rules_dir: Path) -> Path | None:
    raw = str(task["rule_path"] or "").strip()
    if not raw:
        try:
            payload = json.loads(task["input_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        raw = str(payload.get("rule_path") or "").strip() if isinstance(payload, dict) else ""
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    raw = raw.removeprefix("rules/")
    return _safe_rule_path(rules_dir, raw)


def _migrate_tasks(
    connection: sqlite3.Connection,
    rules_dir: Path,
    report: dict[str, Any],
    dry_run: bool,
) -> None:
    rows = connection.execute(
        """
        SELECT task_id, rule_path, rule_sha256, input_json
        FROM tasks
        WHERE rule_sha256 IS NULL OR rule_sha256 = ''
        """
    ).fetchall()
    for task in rows:
        report["counts"]["tasks_scanned"] += 1
        path = _task_rule_path(task, rules_dir)
        if path is None or not path.is_file():
            report["counts"]["tasks_without_hash"] += 1
            if len(report["tasks_without_hash"]) < REPORT_LIMIT:
                report["tasks_without_hash"].append(task["task_id"])
            _append_missing(report, "task", task["task_id"], task["rule_path"], rules_dir)
            continue
        digest = sha256_file(path)
        if not dry_run:
            connection.execute(
                "UPDATE tasks SET rule_sha256 = ? WHERE task_id = ?",
                (digest, task["task_id"]),
            )
        report["counts"]["tasks_hash_written"] += 1


def _migrate_builds(
    connection: sqlite3.Connection,
    report: dict[str, Any],
    dry_run: bool,
) -> None:
    rows = connection.execute(
        """
        SELECT build_id, rule_version, target_rule_version
        FROM builds
        WHERE target_rule_version IS NULL AND rule_version IS NOT NULL
        """
    ).fetchall()
    for build in rows:
        report["counts"]["builds_scanned"] += 1
        if not dry_run:
            connection.execute(
                """
                UPDATE builds SET target_rule_version = ?
                WHERE build_id = ? AND target_rule_version IS NULL
                """,
                (build["rule_version"], build["build_id"]),
            )
        report["counts"]["builds_backfilled"] += 1


def migrate(
    db_path: Path,
    rules_dir: Path,
    *,
    report_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": _iso_now(),
        "dry_run": dry_run,
        "db": db_path.name,
        "rules_dir": rules_dir.name,
        "counts": {
            "batch_sites_scanned": 0,
            "sites_seen": 0,
            "site_rules_written": 0,
            "site_rules_skipped": 0,
            "site_rule_conflicts": 0,
            "rule_files_scanned": 0,
            "rule_versions_written": 0,
            "rule_versions_skipped": 0,
            "rule_version_conflicts": 0,
            "invalid_rule_files": 0,
            "missing_rule_files": 0,
            "tasks_scanned": 0,
            "tasks_hash_written": 0,
            "tasks_without_hash": 0,
            "builds_scanned": 0,
            "builds_backfilled": 0,
        },
        "site_rule_conflicts": [],
        "rule_version_conflicts": [],
        "invalid_rule_files": [],
        "missing_rule_files": [],
        "tasks_without_hash": [],
    }

    TaskStore(db_path)
    connection = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    try:
        connection.execute("BEGIN IMMEDIATE")
        versions, hashes = _scan_rule_files(rules_dir, report)
        selected = _select_versions(versions, report)
        activated = _migrate_site_rules(
            connection, rules_dir, hashes, selected, report, dry_run
        )
        _migrate_rule_versions(connection, selected, activated, report, dry_run)
        _migrate_tasks(connection, rules_dir, report, dry_run)
        _migrate_builds(connection, report, dry_run)
        report["counts"]["site_rule_conflicts"] = len(report["site_rule_conflicts"])
        report["counts"]["rule_version_conflicts"] = len(
            report["rule_version_conflicts"]
        )
        report["counts"]["invalid_rule_files"] = len(
            report["invalid_rule_files"]
        )
        report["counts"]["missing_rule_files"] = len(report["missing_rule_files"])
        if dry_run:
            connection.rollback()
        else:
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    target = report_path or db_path.with_name(
        f"{db_path.name}.migration-{_timestamp()}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"report": report, "path": target}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ecom_crawler.migrate_rules",
        description=(
            "Backfill site_rules, rule_versions, task rule hashes and build "
            "target versions from batch_sites and the rules directory."
        ),
        epilog=(
            "Run while the web service and worker are stopped. Existing site "
            "pointers and rule versions are never overwritten."
        ),
    )
    parser.add_argument("--db", type=Path, required=True, help="existing tasks.db")
    parser.add_argument(
        "--rules-dir", type=Path, required=True, help="directory containing rule YAML"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="report path; defaults to <db>.migration-<timestamp>.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="scan and report without writing ledger rows",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print(f"error: database not found: {args.db}", file=sys.stderr)
        return 2
    if not args.rules_dir.is_dir():
        print(f"error: rules directory not found: {args.rules_dir}", file=sys.stderr)
        return 2
    try:
        result = migrate(
            args.db,
            args.rules_dir,
            report_path=args.report,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001 - command boundary
        print(f"error: migration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    counts = result["report"]["counts"]
    prefix = "dry-run" if args.dry_run else "migrated"
    print(
        f"{prefix}: sites={counts['site_rules_written']} "
        f"versions={counts['rule_versions_written']} "
        f"tasks={counts['tasks_hash_written']} "
        f"builds={counts['builds_backfilled']} "
        f"conflicts={counts['site_rule_conflicts'] + counts['rule_version_conflicts']} "
        f"missing={counts['missing_rule_files']}"
    )
    print(f"report: {result['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
