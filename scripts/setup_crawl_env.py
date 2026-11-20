#!/usr/bin/env python3
"""Create or refresh the shared crawl baseline environment.

The environment is a uv-managed venv outside the repository. It installs
baseline/requirements.lock.txt, optionally installs Scrapling browser
dependencies, runs a small smoke test, and writes a baseline manifest.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = REPO_ROOT / "baseline"
BASELINE_VERSION = "2026.11.20"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="创建或刷新采集爬虫共用基础环境（uv venv，不写全局 site-packages）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python scripts/setup_crawl_env.py\n"
            "  python scripts/setup_crawl_env.py --path D:/crawl-base\n"
            "  python scripts/setup_crawl_env.py --skip-browser\n"
            "  python scripts/setup_crawl_env.py --dry-run --json\n"
        ),
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="环境根目录；默认 Windows 为 %%LOCALAPPDATA%%/crawl-base，其他平台为 ~/.local/share/crawl-base。",
    )
    parser.add_argument(
        "--python",
        default="3.13",
        help="uv 使用的 Python 版本，默认 3.13。",
    )
    parser.add_argument(
        "--index-url",
        default=None,
        help="可选的包索引 URL；不填则使用 uv 当前配置。",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="只装 Python 包，不执行 scrapling install 和浏览器冒烟。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印计划，不创建目录、不安装。",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="stdout 输出 JSON；日志仍写 stderr。",
    )
    return parser.parse_args(argv)


def default_base_dir() -> Path:
    """Return the default shared environment directory."""
    override = os.environ.get("CRAWL_BASE_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "crawl-base"
        return Path.home() / ".crawl-base"
    data = os.environ.get("XDG_DATA_HOME")
    if data:
        return Path(data) / "crawl-base"
    return Path.home() / ".local" / "share" / "crawl-base"


def log(message: str) -> None:
    """Write a timestamped progress line to stderr."""
    print(f"[{datetime.now():%H:%M:%S}] {message}", file=sys.stderr, flush=True)


def venv_python(venv_dir: Path) -> Path:
    """Return the Python executable inside a venv."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def scrapling_executable(venv_dir: Path) -> Path:
    """Return the Scrapling console script inside a venv."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "scrapling.exe"
    return venv_dir / "bin" / "scrapling"


def run(
    command: list[str],
    *,
    capture: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command, streaming output to stderr unless captured."""
    log("run: " + " ".join(str(part) for part in command))
    env = {**os.environ, "PYTHONUTF8": "1"}
    try:
        if capture:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
            )
        return subprocess.run(
            command,
            check=True,
            stdout=sys.stderr,
            stderr=sys.stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"命令不存在: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        suffix = f"\n{detail}" if detail else ""
        raise RuntimeError(f"命令失败（退出码 {exc.returncode}）: {' '.join(command)}{suffix}") from exc


def ensure_uv() -> str:
    """Return the uv executable or raise a clear error."""
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("未找到 uv；先安装 uv，或把 uv 加入 PATH。")
    return uv


def create_venv(uv: str, venv_dir: Path, python_version: str) -> Path:
    """Create a uv venv if needed and return its Python executable."""
    py = venv_python(venv_dir)
    if py.exists():
        log(f"复用已有 venv: {venv_dir}")
        return py
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    run([uv, "venv", "--python", python_version, str(venv_dir)])
    if not py.exists():
        raise RuntimeError(f"venv 创建后未找到 Python: {py}")
    return py


def install_requirements(
    uv: str,
    python: Path,
    requirements: Path,
    index_url: str | None,
) -> None:
    """Install the baseline lock file into the venv."""
    command = [uv, "pip", "install", "--python", str(python), "-r", str(requirements)]
    if index_url:
        command.extend(["--default-index", index_url])
    run(command, timeout=1800)


def install_browser(venv_dir: Path) -> str:
    """Install Scrapling browser dependencies and return a status string."""
    scrapling = scrapling_executable(venv_dir)
    if not scrapling.exists():
        raise RuntimeError(f"未找到 Scrapling 命令: {scrapling}")
    run([str(scrapling), "install"], timeout=3600)
    return "installed"


def smoke_import(python: Path) -> None:
    """Verify the common Python imports."""
    code = (
        "import httpx, requests, bs4, lxml, yaml, pydantic, selectolax, "
        "scrapling, playwright, patchright; print('imports-ok')"
    )
    result = run([str(python), "-c", code], capture=True, timeout=120)
    log(result.stdout.strip())


def smoke_browser(python: Path) -> None:
    """Launch headless Chromium once to verify the browser stack."""
    code = (
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    browser = p.chromium.launch(headless=True)\n"
        "    page = browser.new_page()\n"
        "    page.goto('about:blank')\n"
        "    browser.close()\n"
        "print('browser-ok')\n"
    )
    result = run([str(python), "-c", code], capture=True, timeout=180)
    log(result.stdout.strip())


def package_list(uv: str, python: Path) -> list[dict[str, str]]:
    """Return installed packages as a list of name/version items."""
    result = run(
        [uv, "pip", "list", "--python", str(python), "--format", "json"],
        capture=True,
        timeout=120,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        log("警告: 无法解析 uv pip list 输出，manifest 将不包含包列表")
        return []


def write_manifest(
    base_dir: Path,
    *,
    python: Path,
    browser_status: str,
    packages: list[dict[str, str]],
) -> Path:
    """Write baseline.json and copy the lock file for traceability."""
    base_dir.mkdir(parents=True, exist_ok=True)
    lock_source = BASELINE_DIR / "requirements.lock.txt"
    if lock_source.exists():
        shutil.copyfile(lock_source, base_dir / "requirements.lock.txt")
    manifest = {
        "baseline": BASELINE_VERSION,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "path": str(base_dir),
        "python": str(python),
        "browser": browser_status,
        "package_count": len(packages),
        "packages": packages,
    }
    target = base_dir / "baseline.json"
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_wrapper(base_dir: Path) -> Path:
    """Create a small crawl-python wrapper for the shared venv."""
    bin_dir = base_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    py = venv_python(base_dir / ".venv")
    if os.name == "nt":
        wrapper = bin_dir / "crawl-python.cmd"
        content = f'@echo off\r\n"{py}" %*\r\n'
        wrapper.write_text(content, encoding="utf-8", newline="")
        return wrapper
    wrapper = bin_dir / "crawl-python"
    content = f'#!/bin/sh\nexec "{py}" "$@"\n'
    wrapper.write_text(content, encoding="utf-8", newline="\n")
    wrapper.chmod(0o755)
    return wrapper


def main(argv: list[str] | None = None) -> int:
    """Run the setup workflow."""
    args = parse_args(argv)
    base_dir = (args.path or default_base_dir()).expanduser().resolve()
    requirements = BASELINE_DIR / "requirements.lock.txt"
    if not requirements.exists():
        requirements = BASELINE_DIR / "requirements.txt"
        log("警告: 未找到 requirements.lock.txt，改用 requirements.txt")
    if not requirements.exists():
        log(f"错误: 未找到依赖清单: {requirements}")
        return 1

    plan = {
        "baseline": BASELINE_VERSION,
        "path": str(base_dir),
        "python": args.python,
        "requirements": str(requirements),
        "browser": "skip" if args.skip_browser else "install",
    }
    if args.dry_run:
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            log(f"计划: {json.dumps(plan, ensure_ascii=False)}")
        return 0

    browser_status = "skipped" if args.skip_browser else "pending"
    try:
        uv = ensure_uv()
        python = create_venv(uv, base_dir / ".venv", args.python)
        install_requirements(uv, python, requirements, args.index_url)
        smoke_import(python)

        if not args.skip_browser:
            try:
                browser_status = install_browser(base_dir / ".venv")
                smoke_browser(python)
            except RuntimeError as exc:
                browser_status = "failed"
                log(f"警告: 浏览器依赖安装或冒烟失败: {exc}")

        packages = package_list(uv, python)
        manifest = write_manifest(
            base_dir,
            python=python,
            browser_status=browser_status,
            packages=packages,
        )
        wrapper = write_wrapper(base_dir)
        result = {
            **plan,
            "browser": browser_status,
            "manifest": str(manifest),
            "wrapper": str(wrapper),
            "package_count": len(packages),
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"基线版本: {BASELINE_VERSION}")
            print(f"环境目录: {base_dir}")
            print(f"Python:   {python}")
            print(f"包数量:   {len(packages)}")
            print(f"浏览器:   {browser_status}")
            print(f"清单:     {manifest}")
            print(f"入口:     {wrapper}")
        return 0 if browser_status != "failed" else 1
    except (RuntimeError, OSError) as exc:
        log(f"错误: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
