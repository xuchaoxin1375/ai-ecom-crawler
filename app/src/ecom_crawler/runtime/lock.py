"""Advisory single-worker lock for a SQLite task ledger."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class WorkerLockError(ValueError):
    """Raised when another worker already owns the ledger."""


def _acquire(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def worker_lock(db_path: str | Path) -> Iterator[Path]:
    """Hold an OS-level lock next to the ledger; released on process exit.

    The lock file is intentionally kept after release: the OS lock, not the
    file's existence, decides ownership, so a crash does not leave a stale lock.
    """
    db = Path(db_path)
    lock_path = db.with_name(db.name + ".worker.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        _acquire(fd)
    except OSError as exc:
        os.close(fd)
        raise WorkerLockError(f"another worker is using {db}") from exc
    try:
        payload = f"{os.getpid():<16}".encode("ascii")
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, payload)
        yield lock_path
    finally:
        try:
            _release(fd)
        finally:
            os.close(fd)
