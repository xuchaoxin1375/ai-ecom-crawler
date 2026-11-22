"""Task-owned process and filesystem resource registration and cleanup.

The static runtime needs very little here, but a browser adapter owns child
processes and profile directories.  Register them through this module so a
normal finish, a cancel, or a crashed worker's lease takeover can clean them
up instead of leaving orphans behind.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from .store import TaskStore


def register_process(
    store: TaskStore,
    task_id: str,
    process: subprocess.Popen[Any] | int,
    *,
    resource_id: str | None = None,
    lease_token: int | None = None,
) -> str:
    pid = int(process if isinstance(process, int) else process.pid)
    identifier = resource_id or f"process:{pid}"
    store.add_resource(
        task_id, identifier, "process", pid=pid, lease_token=lease_token
    )
    return identifier


def register_path(
    store: TaskStore,
    task_id: str,
    path: str | Path,
    *,
    resource_id: str | None = None,
    lease_token: int | None = None,
) -> str:
    resolved = Path(path).resolve()
    identifier = resource_id or f"path:{resolved}"
    store.add_resource(
        task_id, identifier, "path", path=str(resolved), lease_token=lease_token
    )
    return identifier


def cleanup_task_resources(
    store: TaskStore,
    task_id: str,
    *,
    grace_seconds: float = 1.0,
    lease_token: int | None = None,
) -> dict[str, int]:
    """Clean every registered resource for one task and return a small report.

    Passing a lease token also includes legacy rows without a token, but never
    touches resources registered by a newer lease holder.
    """
    report = {"processes": 0, "paths": 0, "browser_slots": 0, "failed": 0}
    resources = store.list_resources(task_id)
    if lease_token is not None:
        resources = [
            resource
            for resource in resources
            if resource.get("lease_token") in {None, int(lease_token)}
        ]
    for resource in resources:
        kind = str(resource.get("kind") or "")
        ok = True
        if kind == "process" and resource.get("pid") is not None:
            ok = terminate_process(int(resource["pid"]), grace_seconds=grace_seconds)
            if ok:
                report["processes"] += 1
        elif kind == "path" and resource.get("path"):
            ok = remove_path(Path(str(resource["path"])))
            if ok:
                report["paths"] += 1
        elif kind == "browser_slot":
            store.release_browser_slot(
                task_id, str(resource.get("resource_id") or "")
            )
            report["browser_slots"] += 1
        else:
            ok = False
        if ok:
            store.remove_resource(task_id, str(resource["resource_id"]))
        else:
            report["failed"] += 1
    return report


def cleanup_all_registered(
    store: TaskStore,
    *,
    grace_seconds: float = 1.0,
) -> dict[str, int]:
    report = {"tasks": 0, "processes": 0, "paths": 0, "browser_slots": 0, "failed": 0}
    task_ids = {str(resource["task_id"]) for resource in store.list_resources()}
    for task_id in sorted(task_ids):
        result = cleanup_task_resources(
            store, task_id, grace_seconds=grace_seconds
        )
        report["tasks"] += 1
        for key in ("processes", "paths", "browser_slots", "failed"):
            report[key] += result[key]
    return report


def cleanup_orphan_profiles(
    store: TaskStore,
    out_root: str | Path,
    *,
    dirname: str = "adapter-browser-profile",
    min_age_seconds: float = 24 * 60 * 60,
) -> dict[str, int]:
    """Remove stale adapter profile directories under a task output root.

    The sweep only removes a directory older than ``min_age_seconds`` when no
    live lease protects its task.  Active tasks with a live lease are kept, as
    are non-terminal tasks whose lease state cannot be proven stale.  This is a
    self-healing fallback for profiles left behind by a killed worker; normal
    task cleanup still removes its own registered profile first.
    """
    report = {"scanned": 0, "removed": 0, "kept": 0, "failed": 0}
    root = Path(out_root)
    if not root.is_dir():
        return report
    now = time.time()
    cutoff = now - max(0.0, float(min_age_seconds))
    try:
        task_dirs = list(root.iterdir())
    except OSError:
        report["failed"] += 1
        return report
    for task_dir in task_dirs:
        try:
            if task_dir.is_symlink() or not task_dir.is_dir():
                continue
        except OSError:
            report["failed"] += 1
            continue
        profile = task_dir / dirname
        try:
            if profile.is_symlink() or not profile.is_dir():
                continue
            mtime = profile.stat().st_mtime
        except OSError:
            report["failed"] += 1
            continue
        report["scanned"] += 1
        if mtime > cutoff:
            report["kept"] += 1
            continue
        task = store.get_task(task_dir.name)
        if task is not None:
            live_lease = (
                task.lease_expires_at is not None
                and task.lease_expires_at > now
            )
            if live_lease:
                report["kept"] += 1
                continue
            if (
                task.state in {"RUNNING", "PAUSING", "CANCELLING"}
                and task.lease_expires_at is None
            ):
                report["kept"] += 1
                continue
        if remove_path(profile):
            report["removed"] += 1
        else:
            report["failed"] += 1
    return report


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A terminated child can stay a zombie until its parent reaps it; the
    # kernel still accepts signal 0, so inspect /proc where it is available.
    if Path("/proc").is_dir():
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            state = stat.rsplit(")", 1)[1].strip().split(" ", 1)[0]
            if state == "Z":
                return False
        except (OSError, IndexError):
            pass
    return True


def terminate_process(pid: int, *, grace_seconds: float = 1.0) -> bool:
    """Terminate one process; return True when it is no longer alive."""
    if not pid_alive(pid):
        return True
    if os.name == "nt":
        _terminate_windows(pid, grace_seconds)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        deadline = time.monotonic() + max(0.0, float(grace_seconds))
        while time.monotonic() < deadline:
            if not pid_alive(pid):
                return True
            time.sleep(0.05)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
    deadline = time.monotonic() + max(0.5, float(grace_seconds))
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.05)
    return not pid_alive(pid)


def remove_path(path: Path) -> bool:
    """Remove a registered file or directory, refusing roots and home."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if not resolved.exists() and not resolved.is_symlink():
        return True
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        return False
    try:
        if resolved.is_dir() and not resolved.is_symlink():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
    except OSError:
        return False
    return True


def _windows_pid_alive(pid: int) -> bool:
    import ctypes

    process_query_limited_information = 0x1000
    synchronize = 0x00100000
    still_active = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        process_query_limited_information | synchronize, False, pid
    )
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _terminate_windows(pid: int, grace_seconds: float) -> None:
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=max(2.0, float(grace_seconds) + 2.0),
        )
        return
    except (OSError, subprocess.SubprocessError):
        pass
    import ctypes

    process_terminate = 0x0001
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_terminate, False, pid)
    if not handle:
        return
    try:
        kernel32.TerminateProcess(handle, 1)
    finally:
        kernel32.CloseHandle(handle)
