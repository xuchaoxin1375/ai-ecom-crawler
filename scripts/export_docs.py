#!/usr/bin/env python3
"""export_docs.py - 将 docs/ 导出为可分发 ZIP，并生成或核对 SHA-256 清单。

用法:
    python scripts/export_docs.py
    python scripts/export_docs.py --output-dir dist --name ai-ecom-crawler-docs
    python scripts/export_docs.py --check dist/ai-ecom-crawler-docs.zip

导出包以 docs/ 的内容作为 ZIP 根，内含 manifest.json。清单按相对路径列出
每个文件的大小与 SHA-256，不包含 manifest.json 自身。

需要 Python 3.11+。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT / "docs"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "dist"
DEFAULT_NAME = "ai-ecom-crawler-docs"
MANIFEST_NAME = "manifest.json"
SKIP_DIR_NAMES = {".git", "__pycache__", ".mypy_cache", ".ruff_cache", "dist"}
SKIP_FILE_NAMES = {".DS_Store", "Thumbs.db"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="导出 docs/ 文档包，生成 ZIP 与 SHA-256 清单；或按清单复核已有 ZIP。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python scripts/export_docs.py\n"
            "  python scripts/export_docs.py --output-dir dist --name ai-ecom-crawler-docs\n"
            "  python scripts/export_docs.py --check dist/ai-ecom-crawler-docs.zip\n"
        ),
    )
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="源目录，默认 docs/")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="输出目录，默认 dist/",
    )
    parser.add_argument("--name", default=DEFAULT_NAME, help=f"ZIP 基础名，默认 {DEFAULT_NAME}")
    parser.add_argument("--check", metavar="ZIP", help="复核已有 ZIP 的 manifest.json 与文件哈希")
    parser.add_argument("--verbose", action="store_true", help="输出逐文件进度")
    return parser.parse_args(argv)


def sha256_bytes(payload: bytes) -> str:
    """返回字节内容的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(payload).hexdigest()


def should_skip(path: Path, source: Path) -> bool:
    """判断文件是否应从导出包中排除。"""
    relative = path.relative_to(source)
    if any(part in SKIP_DIR_NAMES for part in relative.parts[:-1]):
        return True
    if path.name in SKIP_FILE_NAMES or path.suffix in SKIP_SUFFIXES:
        return True
    return relative.as_posix() == MANIFEST_NAME


def collect_files(source: Path) -> list[Path]:
    """收集并排序源目录中的文件。"""
    files = [
        path
        for path in source.rglob("*")
        if path.is_file() and not should_skip(path, source)
    ]
    return sorted(files, key=lambda path: path.relative_to(source).as_posix())


def build_manifest(source: Path, files: list[Path], package_name: str) -> dict[str, object]:
    """生成文件清单，包含相对路径、字节数和 SHA-256。"""
    entries = []
    for path in files:
        payload = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(source).as_posix(),
                "bytes": len(payload),
                "sha256": sha256_bytes(payload),
            }
        )
    return {
        "package": package_name,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        ),
        "source_directory": source.name,
        "file_count": len(entries),
        "total_bytes": sum(entry["bytes"] for entry in entries),  # type: ignore[arg-type]
        "files": entries,
    }


def write_zip(
    source: Path,
    files: list[Path],
    output_zip: Path,
    package_name: str,
) -> dict[str, object]:
    """写入 ZIP 与包内清单，返回清单内容。"""
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(source, files, package_name)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(source).as_posix()
            logger.debug("加入: %s", relative)
            archive.write(path, relative)
        archive.writestr(
            MANIFEST_NAME,
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
    return manifest


def check_zip(zip_path: Path) -> int:
    """按包内 manifest.json 复核 ZIP，返回进程退出码。"""
    if not zip_path.is_file():
        logger.error("找不到 ZIP: %s", zip_path)
        return 1

    with zipfile.ZipFile(zip_path) as archive:
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        except KeyError:
            logger.error("ZIP 中缺少 %s: %s", MANIFEST_NAME, zip_path)
            return 1
        entries = manifest.get("files")
        if not isinstance(entries, list):
            logger.error("清单缺少 files 列表: %s", zip_path)
            return 1

        expected = {
            entry["path"]: entry
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        }
        actual = {
            info.filename
            for info in archive.infolist()
            if not info.is_dir() and info.filename != MANIFEST_NAME
        }
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        mismatched = []
        total_bytes = 0
        for name in sorted(expected):
            if name not in actual:
                continue
            logger.debug("校验: %s", name)
            payload = archive.read(name)
            total_bytes += len(payload)
            entry = expected[name]
            if len(payload) != entry.get("bytes") or sha256_bytes(payload) != entry.get("sha256"):
                mismatched.append(name)

        if manifest.get("file_count") != len(expected) or manifest.get("total_bytes") != total_bytes:
            logger.error("清单汇总与文件不一致: %s", zip_path)
            return 1

    if missing or extra or mismatched:
        for name in missing:
            logger.error("清单中有、ZIP 中缺失: %s", name)
        for name in extra:
            logger.error("ZIP 中有、清单中未列: %s", name)
        for name in mismatched:
            logger.error("大小或 SHA-256 不一致: %s", name)
        return 1

    logger.info(
        "复核通过: %s，%d 个文件，%d 字节",
        zip_path,
        len(expected),
        total_bytes,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """入口函数：返回进程退出码。"""
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        if args.check:
            return check_zip(Path(args.check).expanduser().resolve())

        if not args.name or Path(args.name).name != args.name:
            logger.error("--name 只能是文件名，不能包含路径: %s", args.name)
            return 1

        source = Path(args.source).expanduser().resolve()
        if not source.is_dir():
            logger.error("源目录不存在或不是目录: %s", source)
            return 1

        output_dir = Path(args.output_dir).expanduser().resolve()
        output_zip = output_dir / f"{args.name}.zip"
        if output_zip.is_relative_to(source):
            logger.error("输出 ZIP 不能位于源目录内: %s", output_zip)
            return 1

        files = collect_files(source)
        if not files:
            logger.error("源目录没有可导出的文件: %s", source)
            return 1

        logger.info("开始导出: 源=%s，文件=%d", source, len(files))
        manifest = write_zip(source, files, output_zip, args.name)
        logger.info(
            "导出完成: %s，%d 个文件，%d 字节",
            output_zip,
            manifest["file_count"],
            manifest["total_bytes"],
        )
        print(output_zip)
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        logger.error("操作失败: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
