"""Run isolated backend test groups in a Windows job object."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes as win
from dataclasses import dataclass
from pathlib import Path

_CLEANUP_SECONDS = 5


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
        ("flags", win.DWORD), ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t), ("active_limit", win.DWORD),
        ("affinity", ctypes.c_size_t), ("priority", win.DWORD), ("scheduling", win.DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits), ("io", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("times", ctypes.c_int64 * 4), ("page_faults", win.DWORD),
        ("total", win.DWORD), ("active", win.DWORD), ("terminated", win.DWORD),
    ]


class _Job:
    def __init__(self) -> None:
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, win.LPCWSTR], win.HANDLE),
            "SetInformationJobObject": (
                [win.HANDLE, ctypes.c_int, ctypes.c_void_p, win.DWORD], win.BOOL,
            ),
            "OpenProcess": ([win.DWORD, win.BOOL, win.DWORD], win.HANDLE),
            "IsProcessInJob": ([win.HANDLE, win.HANDLE, ctypes.POINTER(win.BOOL)], win.BOOL),
            "AssignProcessToJobObject": ([win.HANDLE, win.HANDLE], win.BOOL),
            "QueryInformationJobObject": (
                [win.HANDLE, ctypes.c_int, ctypes.c_void_p, win.DWORD, ctypes.c_void_p], win.BOOL,
            ),
            "TerminateJobObject": ([win.HANDLE, win.UINT], win.BOOL),
            "CloseHandle": ([win.HANDLE], win.BOOL),
        }
        for name, (argtypes, restype) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes = argtypes
            function.restype = restype
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        # The job handle is not inherited. If this runner dies, Windows closes
        # it and terminates the workers and the children they have spawned.
        if not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, pid: int) -> None:
        access = 0x1000 | 0x0100 | 0x0001  # Query limited information, set quota, terminate.
        process = self.kernel.OpenProcess(access, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            assigned = win.BOOL()
            if not self.kernel.IsProcessInJob(process, self.handle, ctypes.byref(assigned)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not assigned.value and not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.kernel.CloseHandle(process)

    def active(self) -> int:
        counts = _Accounting()
        if not self.kernel.QueryInformationJobObject(
            self.handle, 1, ctypes.byref(counts), ctypes.sizeof(counts), None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(counts.active)

    def drain(self) -> None:
        if self.active() and not self.kernel.TerminateJobObject(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())
        deadline = time.monotonic() + _CLEANUP_SECONDS
        while self.active():
            if time.monotonic() >= deadline:
                raise OSError("test process cleanup could not be confirmed")
            time.sleep(0.05)

    def close(self) -> None:
        self.kernel.CloseHandle(self.handle)


@dataclass
class _Worker:
    name: str
    process: subprocess.Popen[bytes]
    temp: Path
    receipt: Path
    fingerprint: str

    def passed(self) -> bool:
        return (
            self.process.returncode == 0
            and self.receipt.is_file()
            and self.receipt.read_text(encoding="ascii") == self.fingerprint
        )


def admit_windows_worker(
    job: _Job, process: subprocess.Popen[bytes], marker: Path, deadline: float,
) -> None:
    job.assign(process.pid)
    # The venv launcher can spawn the actual interpreter before assignment.
    # Bind the interpreter too, while it is still waiting on stdin.
    while not marker.is_file():
        if process.poll() is not None:
            raise OSError(f"Worker exited before its start gate: {marker.name}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Worker did not reach its start gate in time: {marker.name}")
        time.sleep(0.02)
    job.assign(int(marker.read_text(encoding="ascii")))


def wait_for_start_gate(marker: Path) -> bool:
    staging = marker.with_suffix(".pid.tmp")
    staging.write_text(str(os.getpid()), encoding="ascii")
    staging.replace(marker)
    return sys.stdin.buffer.read(1) == b"1"


def _start_worker(
    job: _Job, command: list[str], root: Path, name: str, fingerprint: str, quiet: bool,
    deadline: float, modules: tuple[str, ...] = (),
) -> _Worker:
    temp = root / name
    temp.mkdir()
    log = root / f"{name}.log"
    receipt = root / f"{name}.passed"
    if modules:
        receipt.with_suffix(".modules").write_text("\n".join(modules), encoding="utf-8")
    env = {
        **os.environ,
        "TMP": str(temp), "TEMP": str(temp), "TMPDIR": str(temp), "PYTHONIOENCODING": "utf-8",
    }
    with log.open("wb") as output:
        process = subprocess.Popen(
            [*command, name, fingerprint, str(receipt), "1" if quiet else "0"],
            env=env, stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            admit_windows_worker(job, process, receipt.with_suffix(".pid"), deadline)
            assert process.stdin is not None
            with process.stdin as gate:
                gate.write(b"1")
        except BaseException:
            if process.stdin is not None:
                process.stdin.close()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=_CLEANUP_SECONDS)
            raise
    return _Worker(name, process, temp, receipt, fingerprint)


def _report(message: str) -> None:
    sys.stderr.write(f"{message}\n")
    sys.stderr.flush()


def run_parallel(
    command: list[str], plan: dict[str, str], *, quiet: bool, timeout: int,
    modules_by_shard: dict[str, tuple[str, ...]] | None = None,
) -> int:
    """Run a validated plan; require a completion receipt from every worker."""
    start = time.monotonic()
    deadline = start + timeout
    workers: list[_Worker] = []
    root = Path(tempfile.mkdtemp(prefix="ecom-tests-parallel-"))
    job = None
    code = 1
    drained = False
    try:
        job = _Job()
        for name, fingerprint in plan.items():
            modules = modules_by_shard[name] if modules_by_shard is not None else ()
            workers.append(
                _start_worker(job, command, root, name, fingerprint, quiet, deadline, modules)
            )
            _report(f"Started {name} (PID {workers[-1].process.pid})")
        pending = workers.copy()
        code = 0
        while pending:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"parallel time limit reached ({timeout}s)")
            for worker in pending.copy():
                if worker.process.poll() is None:
                    continue
                pending.remove(worker)
                passed = worker.passed()
                _report(f"{worker.name}: {'passed' if passed else 'failed or incomplete'}")
                if not passed:
                    code = 1
            if pending:
                time.sleep(0.05)
        if job.active() or any(any(worker.temp.iterdir()) for worker in workers):
            raise OSError("test workers left a process or temporary files behind")
    except KeyboardInterrupt:
        _report("Parallel tests interrupted")
        code = 130
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        _report(f"Parallel tests did not complete: {exc}")
        code = 1
    finally:
        if job is not None:
            try:
                job.drain()
                for worker in workers:
                    worker.process.wait(timeout=_CLEANUP_SECONDS)
                drained = True
            except (OSError, subprocess.SubprocessError) as exc:
                _report(f"Parallel cleanup could not be confirmed: {exc}")
                code = 1
            finally:
                job.close()
        if drained:
            try:
                for name in plan:
                    temp = root / name
                    if temp.exists():
                        shutil.rmtree(temp)
            except OSError as exc:
                _report(f"Temporary file cleanup failed: {exc}")
                code = 1

    for name in plan:
        log = root / f"{name}.log"
        if log.is_file():
            _report(f"--- {name} ---")
            try:
                _report(log.read_text(encoding="utf-8", errors="replace").rstrip())
            except OSError as exc:
                _report(f"Could not read {name} log: {exc}")
                code = 1
    if code == 0:
        try:
            shutil.rmtree(root)
        except OSError as exc:
            _report(f"Could not remove parallel run directory: {exc}")
            code = 1
    if code != 0:
        _report(f"Parallel test diagnostics: {root}; rerun with a serial test command")
    _report(f"Parallel wall clock: {time.monotonic() - start:.2f}s")
    return code
