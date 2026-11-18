#!/usr/bin/env python3
"""check_docs_links.py - 检查 docs/ 内 Markdown 相对链接是否指向真实文件。

用法:
    python scripts/check_docs_links.py
    python scripts/check_docs_links.py --docs docs --verbose

只校验相对路径与文件是否存在，不校验锚点（`#...`）和外部网址。相对链接必须
落在 docs/ 目录内，指向目录外视为断链，因为导出包要求正文链接全部在包内。

需要 Python 3.11+。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCS = REPO_ROOT / "docs"
MD_SUFFIXES = {".md", ".markdown"}

CODE_SPAN_RE = re.compile(r"`[^`]*`")
LINK_RE = re.compile(
    r"!?\[(?P<text>[^\]]*)\]\(\s*"
    r"(?P<target><[^>]*>|[^)\s]+)"
    r"""(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)"""
)
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
FENCE_RE = re.compile(r"^\s{0,3}(?P<fence>`{3,}|~{3,})")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="检查 docs/ 内 Markdown 相对链接，输出断链位置并以非零码退出。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python scripts/check_docs_links.py\n"
            "  python scripts/check_docs_links.py --docs docs --verbose\n"
        ),
    )
    parser.add_argument(
        "--docs",
        default=str(DEFAULT_DOCS),
        help="Markdown 根目录，默认 docs/",
    )
    parser.add_argument("--verbose", action="store_true", help="逐文件输出检查结果")
    return parser.parse_args(argv)


def iter_markdown_files(docs_root: Path) -> list[Path]:
    """返回排序后的 Markdown 文件列表。"""
    files = [
        path
        for path in docs_root.rglob("*")
        if path.is_file() and path.suffix.lower() in MD_SUFFIXES
    ]
    return sorted(files, key=lambda path: path.relative_to(docs_root).as_posix())


def mask_code_spans(line: str) -> str:
    """把行内代码替换为等长空格，避免把示例语法当成真实链接。"""
    return CODE_SPAN_RE.sub(lambda match: " " * len(match.group(0)), line)


def iter_links(text: str) -> list[tuple[int, str, str]]:
    """按行返回 (行号, 链接文字, 目标)，跳过围栏代码块。"""
    links: list[tuple[int, str, str]] = []
    fence: str | None = None
    for number, raw_line in enumerate(text.splitlines(), start=1):
        fence_match = FENCE_RE.match(raw_line)
        if fence_match:
            marker = fence_match.group("fence")
            if fence is None:
                fence = marker[0] * 3
            elif raw_line.strip().startswith(fence):
                fence = None
            continue
        if fence is not None:
            continue
        for match in LINK_RE.finditer(mask_code_spans(raw_line)):
            target = match.group("target").strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1].strip()
            links.append((number, match.group("text").strip(), target))
    return links


def check_target(source: Path, docs_root: Path, target: str) -> str | None:
    """返回断链原因；链接正常时返回 None。"""
    if not target or target.startswith("#"):
        return None
    if target.startswith("//") or SCHEME_RE.match(target):
        return None
    if target.startswith("/"):
        return "以 / 开头，无法在文档包内解析"

    raw_path = unquote(target.split("#", 1)[0])
    if not raw_path:
        return None
    resolved = (source.parent / raw_path).resolve()
    if not resolved.exists():
        return "目标不存在"
    try:
        resolved.relative_to(docs_root)
    except ValueError:
        return "目标在 docs/ 之外，导出包内会断链"
    return None


def main(argv: list[str] | None = None) -> int:
    """入口函数：返回进程退出码。"""
    args = parse_args(argv)
    docs_root = Path(args.docs).expanduser().resolve()
    if not docs_root.is_dir():
        print(f"错误: 文档目录不存在: {docs_root}", file=sys.stderr)
        return 1

    files = iter_markdown_files(docs_root)
    if not files:
        print(f"错误: 没有找到 Markdown 文件: {docs_root}", file=sys.stderr)
        return 1

    broken: list[tuple[Path, int, str, str, str]] = []
    total_links = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        count = 0
        for number, label, target in iter_links(text):
            count += 1
            total_links += 1
            reason = check_target(path, docs_root, target)
            if reason is not None:
                broken.append((path, number, label, target, reason))
        if args.verbose:
            print(f"检查: {path.relative_to(docs_root).as_posix()}，{count} 条链接")

    for path, number, label, target, reason in broken:
        relative = path.relative_to(docs_root).as_posix()
        print(f"断链: {relative}:{number}: [{label}]({target}) - {reason}")

    if broken:
        print(f"失败: {len(files)} 个文件，{total_links} 条链接，{len(broken)} 条断链")
        return 1

    print(f"通过: {len(files)} 个文件，{total_links} 条链接，全部可解析")
    return 0


if __name__ == "__main__":
    sys.exit(main())
