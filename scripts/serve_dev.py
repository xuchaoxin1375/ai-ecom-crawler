#!/usr/bin/env python3
"""serve_dev.py - 管理本地面板的唯一开发实例。

默认端口固定为 8765。脚本负责启动、停止和重启同一个实例，并在
``.runtime/`` 保存这次启动的参数和日志，避免每次由新进程占用新端口。

用法:
    python scripts/serve_dev.py status
    python scripts/serve_dev.py start --db /path/to/tasks.db --out-root /path/to/out --rules-dir /path/to/rules
    python scripts/serve_dev.py restart
    python scripts/serve_dev.py stop
    python scripts/serve_dev.py prune --ports 8775,8877-8879

退出码:
    status  0 表示 8765 正在运行且代码/前端不需要重启；1 表示未运行或已落后。
    start   0 表示健康检查通过；1 表示启动失败或端口已被占用。
    stop    0 表示已停止或本来未运行；1 表示仍有进程无法停止。
    prune   0 表示请求清理的实例都已处理；1 表示有失败项。
"""

from __future__ import annotations

import argparse
import json
import locale
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
APP_SRC = APP_DIR / "src"
RUNTIME_DIR = REPO_ROOT / ".runtime"
CANONICAL_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
DEV_IDENTITY_PATH = "/api/dev/identity"
START_TIMEOUT = 30.0
STOP_TIMEOUT = 10.0
HEALTH_TIMEOUT = 0.8
SUBPROCESS_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

logger = logging.getLogger("serve_dev")

# The dev script may run with a plain interpreter before the package is
# installed; add the source tree so the identity helpers stay shared with the
# application instead of being copied here.
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))
from ecom_crawler.runtime.identity import (
    code_fingerprint,
    frontend_info,
    git_info,
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def decode_output(data: bytes) -> str:
    """Decode console output from Windows tools or POSIX commands."""
    for encoding in ("utf-8", locale.getpreferredencoding(False), "mbcs"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def run_command(args: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        capture_output=True,
        timeout=timeout,
        check=False,
        creationflags=SUBPROCESS_FLAGS,
    )


def parse_ports(value: str) -> list[int]:
    ports: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"invalid port range: {item}")
            if end - start > 1000:
                raise ValueError(f"port range is too large: {item}")
            ports.update(range(start, end + 1))
        else:
            ports.add(int(item))
    for port in ports:
        if not 1 <= port <= 65535:
            raise ValueError(f"invalid port: {port}")
    return sorted(ports)


def state_path(port: int) -> Path:
    return RUNTIME_DIR / f"serve-{port}.json"


def load_state(port: int) -> dict[str, Any] | None:
    path = state_path(port)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取实例状态失败 %s: %s", path, exc)
        return None
    return raw if isinstance(raw, dict) else None


def save_state(state: dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    path = state_path(int(state["port"]))
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def clear_state(port: int) -> None:
    try:
        state_path(port).unlink()
    except FileNotFoundError:
        return


def state_ports() -> list[int]:
    if not RUNTIME_DIR.is_dir():
        return []
    ports: list[int] = []
    for path in RUNTIME_DIR.glob("serve-*.json"):
        match = re.fullmatch(r"serve-(\d+)\.json", path.name)
        if match:
            ports.append(int(match.group(1)))
    return sorted(set(ports))


def health(port: int, timeout: float = HEALTH_TIMEOUT) -> dict[str, Any] | None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for name in ("127.0.0.1", "[::1]"):
        for path in (DEV_IDENTITY_PATH, "/api/health"):
            request = urllib.request.Request(
                f"http://{name}:{port}{path}",
                headers={"Accept": "application/json"},
            )
            try:
                with opener.open(request, timeout=timeout) as response:
                    if response.status != 200:
                        continue
                    payload = json.loads(response.read().decode("utf-8"))
            except (OSError, ValueError, urllib.error.URLError):
                continue
            if isinstance(payload, dict) and payload.get("status") == "ok":
                return payload
    return None


def _windows_listener_pids(port: int) -> list[int]:
    try:
        result = run_command(["netstat", "-ano", "-p", "tcp"])
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids: set[int] = set()
    for line in decode_output(result.stdout).splitlines():
        parts = line.split()
        if len(parts) < 5 or not parts[0].upper().startswith("TCP"):
            continue
        if parts[1].rsplit(":", 1)[-1] != str(port):
            continue
        # Only LISTENING owns the port. Closed/time-wait/fin-wait rows can
        # still carry the local port and a dead PID, which previously blocked
        # restart after a clean stop.
        if parts[3].upper() not in {"LISTEN", "LISTENING"}:
            continue
        candidate = parts[-1]
        if candidate.isdigit() and int(candidate) > 0:
            pids.add(int(candidate))
    return sorted(pids)


def _posix_listener_pids(port: int) -> list[int]:
    lsof = shutil.which("lsof")
    if lsof:
        try:
            result = run_command(
                [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"]
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None:
            pids = {
                int(line)
                for line in decode_output(result.stdout).splitlines()
                if line.strip().isdigit()
            }
            if pids:
                return sorted(pids)
    ss = shutil.which("ss")
    if ss:
        try:
            result = run_command([ss, "-ltnp", f"sport = :{port}"])
        except (OSError, subprocess.TimeoutExpired):
            return []
        return sorted(
            {int(match.group(1)) for match in re.finditer(r"pid=(\d+)", decode_output(result.stdout))}
        )
    return []


def listener_pids(port: int) -> list[int]:
    if os.name == "nt":
        return _windows_listener_pids(port)
    return _posix_listener_pids(port)


def listening_ports() -> set[int] | None:
    """Return local TCP ports that are currently listening.

    ``--scan`` uses this once instead of probing every closed port with an HTTP
    timeout.  ``None`` means the platform helper is unavailable; callers fall
    back to probing the requested range.
    """
    if os.name == "nt":
        try:
            result = run_command(["netstat", "-ano", "-p", "tcp"])
        except (OSError, subprocess.TimeoutExpired):
            return None
        ports: set[int] = set()
        for line in decode_output(result.stdout).splitlines():
            parts = line.split()
            if len(parts) < 5 or not parts[0].upper().startswith("TCP"):
                continue
            candidate = parts[1].rsplit(":", 1)[-1]
            if candidate.isdigit() and 1 <= int(candidate) <= 65535:
                ports.add(int(candidate))
        return ports
    ss = shutil.which("ss")
    if ss:
        try:
            result = run_command([ss, "-ltnH"])
        except (OSError, subprocess.TimeoutExpired):
            return None
        ports = set()
        for line in decode_output(result.stdout).splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            candidate = parts[3].rsplit(":", 1)[-1]
            if candidate.isdigit() and 1 <= int(candidate) <= 65535:
                ports.add(int(candidate))
        return ports
    lsof = shutil.which("lsof")
    if lsof:
        try:
            result = run_command([lsof, "-nP", "-iTCP", "-sTCP:LISTEN", "-F", "n"])
        except (OSError, subprocess.TimeoutExpired):
            return None
        ports = set()
        for line in decode_output(result.stdout).splitlines():
            if not line.startswith("n"):
                continue
            candidate = line.rsplit(":", 1)[-1]
            if candidate.isdigit() and 1 <= int(candidate) <= 65535:
                ports.add(int(candidate))
        return ports
    return None


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            result = run_command(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        for line in decode_output(result.stdout).splitlines():
            fields = line.split('","')
            if len(fields) >= 2 and fields[1].strip('"') == str(pid):
                return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_command_line(pid: int) -> str | None:
    """Return the command line for a PID without importing psutil."""
    if os.name == "nt":
        script = (
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
            f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CommandLine'
        )
        try:
            result = run_command(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
    else:
        try:
            result = run_command(["ps", "-p", str(pid), "-o", "args="])
        except (OSError, subprocess.TimeoutExpired):
            return None
    text = decode_output(result.stdout).strip()
    return text or None


def command_is_ecom_serve(command: str | None) -> bool:
    if not command:
        return False
    lowered = command.lower()
    if "ecom_crawler" not in lowered and "ecom-crawler" not in lowered:
        return False
    return re.search(r"(^|\s)serve(\s|$)", lowered) is not None


def is_ecom_serve(pid: int) -> bool:
    return command_is_ecom_serve(process_command_line(pid))


def split_command_line(command: str) -> list[str]:
    if os.name == "nt":
        return [token.strip("\"'") for token in shlex.split(command, posix=False)]
    return shlex.split(command, posix=True)


def parse_serve_command(command: str) -> dict[str, Any] | None:
    """Parse a running ``serve`` command into values the script can restart."""
    tokens = split_command_line(command)
    try:
        index = tokens.index("serve")
    except ValueError:
        return None
    args = tokens[index + 1 :]
    value_options = {
        "--db": "db",
        "--out-root": "out_root",
        "--rules-dir": "rules_dir",
        "--host": "host",
        "--port": "port",
        "--proxy": "proxy",
        "--max-tasks": "max_tasks",
        "--max-builds": "max_builds",
    }
    flag_options = {"--no-worker": "no_worker", "--read-only": "read_only"}
    parsed: dict[str, Any] = {"extra": []}
    cursor = 0
    while cursor < len(args):
        item = args[cursor]
        if item in value_options:
            if cursor + 1 >= len(args):
                return None
            value: Any = args[cursor + 1]
            key = value_options[item]
            if key in {"port", "max_tasks", "max_builds"}:
                try:
                    value = int(value)
                except ValueError:
                    return None
            parsed[key] = value
            cursor += 2
        elif item in flag_options:
            parsed[flag_options[item]] = True
            cursor += 1
        elif item == "--access-token":
            cursor += 2
        elif item.startswith("--access-token="):
            cursor += 1
        elif item == "--":
            parsed["extra"].extend(args[cursor + 1 :])
            break
        else:
            parsed["extra"].append(item)
            cursor += 1
    if not parsed.get("db") or not parsed.get("out_root"):
        return None
    return parsed


def adopt_state(port: int) -> dict[str, Any] | None:
    """Read an existing serve instance's command line so restart can take over."""
    for pid in listener_pids(port):
        command = process_command_line(pid)
        if not command_is_ecom_serve(command):
            continue
        parsed = parse_serve_command(command or "")
        if parsed is None:
            continue
        parsed["pid"] = pid
        parsed["port"] = port
        parsed.setdefault("host", DEFAULT_HOST)
        parsed["log"] = str(RUNTIME_DIR / f"serve-{port}.log")
        parsed["started_at"] = None
        return parsed
    return None


def terminate_pid(pid: int, *, force: bool) -> None:
    if os.name == "nt":
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        try:
            run_command(command, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("taskkill %s 失败: %s", pid, exc)
        return
    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        logger.warning("无法结束进程 %s: %s", pid, exc)


def wait_stopped(port: int, pids: set[int], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health(port) is None and not any(process_alive(pid) for pid in pids):
            return True
        time.sleep(0.25)
    return health(port) is None and not any(process_alive(pid) for pid in pids)


def stop_port(
    port: int,
    *,
    force: bool,
    timeout: float = STOP_TIMEOUT,
    preserve_state: bool = False,
) -> int:
    current = health(port)
    live_pids = set(listener_pids(port))
    state = load_state(port)
    if current is not None:
        health_pid = current.get("pid")
        if isinstance(health_pid, int):
            live_pids.add(health_pid)
    if state is not None:
        state_pid = state.get("pid")
        if isinstance(state_pid, int) and process_alive(state_pid):
            live_pids.add(state_pid)
    if not live_pids and current is None:
        clear_state(port)
        print(f"端口 {port} 没有运行中的实例")
        return 0
    if (
        current is None
        and not force
        and state is None
        and not any(is_ecom_serve(pid) for pid in live_pids)
    ):
        print(
            f"端口 {port} 被非 ecom-crawler 进程占用（PID "
            f"{', '.join(str(pid) for pid in sorted(live_pids))}）；"
            "使用 --force 才会终止。",
            file=sys.stderr,
        )
        return 1
    logger.warning("停止会中断在途采集任务和构建；构建重启后可继续。")
    for pid in sorted(live_pids):
        if process_alive(pid):
            terminate_pid(pid, force=False)
    if not wait_stopped(port, live_pids, timeout):
        for pid in sorted(live_pids):
            if process_alive(pid):
                terminate_pid(pid, force=True)
        wait_stopped(port, live_pids, 5.0)
    if health(port) is None and not any(process_alive(pid) for pid in live_pids):
        if not preserve_state:
            clear_state(port)
        print(f"已停止端口 {port}")
        return 0
    print(f"端口 {port} 仍未停止；请检查进程 {sorted(live_pids)}", file=sys.stderr)
    return 1


def current_identity() -> dict[str, Any]:
    return {
        "code_fingerprint": code_fingerprint(APP_SRC / "ecom_crawler"),
        "frontend": frontend_info(APP_DIR / "frontend" / "dist"),
        "git": git_info(REPO_ROOT),
    }


def stale_reasons(health_payload: dict[str, Any], current: dict[str, Any]) -> tuple[list[str], list[str]]:
    restart: list[str] = []
    refresh: list[str] = []
    if health_payload.get("code_fingerprint") != current["code_fingerprint"]:
        restart.append("后端代码已变化，需要重启")
    server_frontend = health_payload.get("frontend") or {}
    current_frontend = current["frontend"]
    if not server_frontend.get("mounted") and current_frontend.get("exists"):
        restart.append("前端构建在服务启动后才出现，需要重启")
    elif (
        server_frontend.get("mounted")
        and current_frontend.get("exists")
        and server_frontend.get("index_sha256") != current_frontend.get("sha256")
    ):
        refresh.append("前端构建已更新，刷新浏览器即可")
    server_git = health_payload.get("git") or {}
    current_git = current["git"]
    if (
        not health_payload.get("code_fingerprint")
        and server_git.get("commit")
        and current_git.get("commit")
        and server_git.get("commit") != current_git.get("commit")
    ):
        restart.append("代码提交与当前仓库不同")
    return restart, refresh


def status_rows(ports: list[int]) -> list[dict[str, Any]]:
    current = current_identity()
    rows: list[dict[str, Any]] = []
    for port in ports:
        payload = health(port)
        pids = listener_pids(port)
        state = load_state(port)
        restart: list[str] = []
        refresh: list[str] = []
        ecom_serve = False
        if payload is not None:
            restart, refresh = stale_reasons(payload, current)
        elif pids:
            ecom_serve = any(is_ecom_serve(pid) for pid in pids)
        row = {
            "port": port,
            "canonical": port == CANONICAL_PORT,
            "running": payload is not None or bool(pids),
            "health": payload,
            "listener_pids": pids,
            "ecom_serve": ecom_serve,
            "state": state,
            "restart_reasons": restart,
            "refresh_hints": refresh,
            "ok": payload is not None and not restart,
        }
        rows.append(row)
    return rows


def print_status(rows: list[dict[str, Any]], current: dict[str, Any]) -> None:
    if not rows:
        print("没有运行中的 ecom-crawler 实例")
        return
    for row in rows:
        port = row["port"]
        marker = "●" if row["running"] else "○"
        label = "规范入口" if row["canonical"] else "非规范端口"
        print(f"{marker} {port}  {label}")
        payload = row["health"]
        if payload is None:
            pids = row["listener_pids"]
            if pids and row["ecom_serve"]:
                print(
                    f"   运行中（本地身份接口不可用，可能是旧版或需要认证）；"
                    f"PID {', '.join(str(pid) for pid in pids)}"
                )
                print("   可用 restart 接管并加载当前代码")
            elif pids:
                print(f"   端口被 PID {', '.join(str(pid) for pid in pids)} 占用；不是 ecom-crawler")
            else:
                print("   未运行")
            continue
        frontend = payload.get("frontend") or {}
        git = payload.get("git") or {}
        commit = str(git.get("commit") or "-")[:8]
        dirty = " dirty" if git.get("dirty") else ""
        mounted = "已挂载" if frontend.get("mounted") else "未挂载"
        pids = row["listener_pids"]
        pid = payload.get("pid") or (pids[0] if pids else None)
        print(
            f"   PID {pid}  {payload.get('started_at') or '-'}  "
            f"{payload.get('worker')}  v{payload.get('version')}"
        )
        print(f"   账本 {payload.get('db')}")
        print(
            f"   代码 {commit}{dirty}  指纹 {payload.get('code_fingerprint') or '-'}  "
            f"前端 {frontend.get('kind') or '未知'}（{mounted}）"
        )
        for reason in row["restart_reasons"]:
            print(f"   ⚠ {reason}")
        for hint in row["refresh_hints"]:
            print(f"   ↻ {hint}")
        if not row["restart_reasons"] and not row["refresh_hints"]:
            print("   状态：与当前工作区一致")
    canonical = next((row for row in rows if row["canonical"]), None)
    if canonical is None:
        print(f"没有检查规范端口 {CANONICAL_PORT}")
    elif not canonical["running"]:
        print(f"规范入口 {CANONICAL_PORT} 未运行；启动后使用 http://127.0.0.1:{CANONICAL_PORT}/")
    current_git = current["git"]
    if current_git.get("commit"):
        print(f"当前仓库 {str(current_git['commit'])[:8]}{' dirty' if current_git.get('dirty') else ''}")


def status_command(args: argparse.Namespace) -> int:
    ports = {CANONICAL_PORT, *state_ports()}
    if args.port:
        ports.add(args.port)
    if args.ports:
        ports.update(parse_ports(args.ports))
    if args.scan:
        requested = parse_ports(args.scan)
        open_ports = listening_ports()
        ports.update(port for port in requested if open_ports is None or port in open_ports)
    rows = status_rows(sorted(ports))
    current = current_identity()
    if args.json:
        print(
            json.dumps(
                {
                    "canonical_port": CANONICAL_PORT,
                    "ok": any(row["canonical"] and row["ok"] for row in rows),
                    "current": current,
                    "instances": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_status(rows, current)
    canonical = next((row for row in rows if row["canonical"]), None)
    return 0 if canonical is not None and canonical["ok"] else 1


def app_python() -> Path:
    for candidate in (
        APP_DIR / ".venv" / "Scripts" / "python.exe",
        APP_DIR / ".venv" / "bin" / "python",
    ):
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def read_log_tail(path: Path, lines: int = 25) -> str:
    try:
        text = decode_output(path.read_bytes())
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def resolve_value(
    explicit: Any,
    state: dict[str, Any] | None,
    key: str,
    default: Any = None,
) -> Any:
    if explicit is not None:
        return explicit
    if state is not None and key in state:
        return state[key]
    return default


def start_command(args: argparse.Namespace) -> int:
    port = int(args.port)
    if not 1 <= port <= 65535:
        print(f"无效端口: {port}", file=sys.stderr)
        return 1
    state = load_state(port)
    db_value = resolve_value(args.db, state, "db")
    out_value = resolve_value(args.out_root, state, "out_root")
    if not db_value or not out_value:
        print(
            "缺少 --db 或 --out-root；第一次启动需要同时提供，"
            "之后 restart 会复用 .runtime 中的参数。",
            file=sys.stderr,
        )
        return 1
    db = str(Path(str(db_value)).expanduser().resolve())
    out_root = str(Path(str(out_value)).expanduser().resolve())
    rules_value = resolve_value(args.rules_dir, state, "rules_dir")
    rules_dir = str(Path(str(rules_value)).expanduser().resolve()) if rules_value else None
    host = resolve_value(args.host, state, "host", DEFAULT_HOST)
    no_worker = bool(resolve_value(args.no_worker, state, "no_worker", False))
    read_only = bool(resolve_value(args.read_only, state, "read_only", False))
    proxy = resolve_value(args.proxy, state, "proxy")
    max_tasks = resolve_value(args.max_tasks, state, "max_tasks")
    max_builds = resolve_value(args.max_builds, state, "max_builds")
    extra = list(args.extra or [])
    if not extra and state is not None:
        extra = list(state.get("extra") or [])
    if any(item == "--access-token" or item.startswith("--access-token=") for item in extra):
        print(
            "不要把 --access-token 放在脚本参数里；请用 ECOM_SERVE_TOKEN 环境变量，"
            "脚本不会持久化密钥。",
            file=sys.stderr,
        )
        return 1
    existing = health(port)
    if existing is not None or listener_pids(port):
        print(
            f"端口 {port} 已有实例运行；先运行 status 查看，或用 restart 替换。",
            file=sys.stderr,
        )
        if existing is not None:
            print(
                f"  PID {existing.get('pid')}  {existing.get('started_at')}  "
                f"{existing.get('worker')}",
                file=sys.stderr,
            )
        return 1
    serve_args = ["serve", "--db", db, "--out-root", out_root]
    if rules_dir:
        serve_args += ["--rules-dir", rules_dir]
    serve_args += ["--host", str(host), "--port", str(port)]
    if no_worker:
        serve_args.append("--no-worker")
    if read_only:
        serve_args.append("--read-only")
    if proxy:
        serve_args += ["--proxy", str(proxy)]
    if max_tasks is not None:
        serve_args += ["--max-tasks", str(max_tasks)]
    if max_builds is not None:
        serve_args += ["--max-builds", str(max_builds)]
    serve_args += extra
    python = app_python()
    command = [str(python), "-X", "utf8", "-m", "ecom_crawler", *serve_args]
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RUNTIME_DIR / f"serve-{port}.log"
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    existing_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(APP_SRC) if not existing_path else str(APP_SRC) + os.pathsep + existing_path
    )
    log_file = log_path.open("a", encoding="utf-8", errors="replace")
    kwargs: dict[str, Any] = {
        "cwd": str(REPO_ROOT),
        "env": environment,
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        log_file.close()
        print(f"启动失败: {exc}", file=sys.stderr)
        return 1
    save_state(
        {
            "pid": process.pid,
            "port": port,
            "host": host,
            "db": db,
            "out_root": out_root,
            "rules_dir": rules_dir,
            "no_worker": no_worker,
            "read_only": read_only,
            "proxy": proxy,
            "max_tasks": max_tasks,
            "max_builds": max_builds,
            "extra": extra,
            "log": str(log_path),
            "started_at": now_iso(),
        }
    )
    deadline = time.monotonic() + float(args.timeout)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        payload = health(port)
        if payload is not None:
            log_file.close()
            print(f"已启动 http://127.0.0.1:{port}/")
            print(f"PID {process.pid}  日志 {log_path}")
            return 0
        time.sleep(0.25)
    log_file.close()
    if process.poll() is None:
        terminate_pid(process.pid, force=False)
        time.sleep(1.0)
        if process.poll() is None:
            terminate_pid(process.pid, force=True)
    tail = read_log_tail(log_path)
    print(f"启动失败或健康检查超时；日志 {log_path}", file=sys.stderr)
    if tail:
        print(tail, file=sys.stderr)
    return 1


def restart_command(args: argparse.Namespace) -> int:
    port = int(args.port)
    state = load_state(port)
    if state is None:
        state = adopt_state(port)
        if state is not None:
            save_state(state)
    if state is None and (args.db is None or args.out_root is None):
        print(
            "没有可复用的启动参数；第一次 restart 需要提供 --db 和 --out-root。",
            file=sys.stderr,
        )
        return 1
    stopped = stop_port(
        port,
        force=bool(args.force),
        timeout=float(args.stop_timeout),
        preserve_state=True,
    )
    if stopped != 0:
        return stopped
    return start_command(args)


def prune_command(args: argparse.Namespace) -> int:
    ports: set[int] = set()
    if args.ports:
        ports.update(parse_ports(args.ports))
    if args.scan:
        requested = parse_ports(args.scan)
        open_ports = listening_ports()
        ports.update(port for port in requested if open_ports is None or port in open_ports)
    if not ports:
        ports.update(port for port in state_ports() if port != CANONICAL_PORT)
    if not ports:
        print("没有指定端口；使用 --ports 或 --scan 指定要清理的实例。", file=sys.stderr)
        return 1
    failures = 0
    for port in sorted(ports):
        if port == CANONICAL_PORT and not args.include_canonical:
            print(f"跳过规范端口 {port}（需要 --include-canonical）")
            continue
        payload = health(port)
        if payload is None:
            pids = listener_pids(port)
            if not any(is_ecom_serve(pid) for pid in pids):
                print(f"跳过 {port}：没有 ecom-crawler 健康响应")
                continue
            if not args.yes:
                print(
                    f"将停止 {port}（旧版或需要认证）；"
                    f"PID {', '.join(str(pid) for pid in pids)}"
                )
                continue
        elif not args.yes:
            print(
                f"将停止 {port}：PID {payload.get('pid')}  "
                f"{payload.get('started_at')}  {payload.get('db')}"
            )
            continue
        if stop_port(port, force=bool(args.force)) != 0:
            failures += 1
    if not args.yes:
        print("这是预演；确认后加 --yes 执行。")
    return 0 if failures == 0 else 1


def add_start_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", help="任务账本路径；第一次启动必须提供，restart 可复用")
    parser.add_argument("--out-root", help="输出目录；第一次启动必须提供，restart 可复用")
    parser.add_argument("--rules-dir", help="受管规则包目录")
    parser.add_argument("--host", help=f"监听地址，默认 {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=CANONICAL_PORT, help=f"端口，默认 {CANONICAL_PORT}")
    parser.add_argument("--no-worker", action="store_true", default=None, help="只提供 API，不托管 worker")
    parser.add_argument("--read-only", action="store_true", default=None, help="只读预览")
    parser.add_argument("--proxy", help="出口代理 URL")
    parser.add_argument("--max-tasks", type=int, help="托管采集并发")
    parser.add_argument("--max-builds", type=int, help="规则分析并发")
    parser.add_argument("--timeout", type=float, default=START_TIMEOUT, help="等待健康检查的秒数")
    parser.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="传给 serve 的其余参数，放在 -- 之后；不要放 --access-token",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="管理 8765 上的唯一 ecom-crawler 开发实例",
        epilog=(
            "示例:\n"
            "  python scripts/serve_dev.py status\n"
            "  python scripts/serve_dev.py status --scan 8700-8899\n"
            "  python scripts/serve_dev.py start --db /path/to/tasks.db "
            "--out-root /path/to/out --rules-dir /path/to/rules\n"
            "  python scripts/serve_dev.py restart\n"
            "  python scripts/serve_dev.py prune --ports 8775,8877-8879"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="查看实例、代码指纹和前端构建")
    status_parser.add_argument("--port", type=int, default=CANONICAL_PORT)
    status_parser.add_argument("--ports", help="逗号分隔的端口或范围，例如 8765,8877-8879")
    status_parser.add_argument("--scan", help="扫描端口范围，例如 8700-8899")
    status_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    status_parser.set_defaults(handler=status_command)

    start_parser = subparsers.add_parser("start", help="启动 8765 实例")
    add_start_arguments(start_parser)
    start_parser.set_defaults(handler=start_command)

    stop_parser = subparsers.add_parser("stop", help="停止实例")
    stop_parser.add_argument("--port", type=int, default=CANONICAL_PORT)
    stop_parser.add_argument("--force", action="store_true", help="允许终止非 ecom-crawler 或不响应的进程")
    stop_parser.add_argument("--timeout", type=float, default=STOP_TIMEOUT, dest="stop_timeout")
    stop_parser.set_defaults(handler=lambda args: stop_port(
        int(args.port), force=bool(args.force), timeout=float(args.stop_timeout)
    ))

    restart_parser = subparsers.add_parser("restart", help="停止后按保存的参数重启")
    add_start_arguments(restart_parser)
    restart_parser.add_argument("--force", action="store_true", help="停止阶段允许强制终止")
    restart_parser.add_argument("--stop-timeout", type=float, default=STOP_TIMEOUT)
    restart_parser.set_defaults(handler=restart_command)

    prune_parser = subparsers.add_parser("prune", help="清理非规范实例")
    prune_parser.add_argument("--ports", help="逗号分隔的端口或范围")
    prune_parser.add_argument("--scan", help="扫描端口范围")
    prune_parser.add_argument("--yes", action="store_true", help="实际执行；默认只预演")
    prune_parser.add_argument("--force", action="store_true", help="允许强制终止")
    prune_parser.add_argument(
        "--include-canonical",
        action="store_true",
        help="允许清理 8765（危险）",
    )
    prune_parser.set_defaults(handler=prune_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logger.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
