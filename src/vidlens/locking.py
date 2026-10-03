"""cross-process write locks.

One lock file per cache directory — granularity is a single video, so
concurrent vidlens runs on *different* videos never block each other.
Windows uses msvcrt.locking, POSIX uses fcntl.flock.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterator
from pathlib import Path

from .agentio import VidlensError


class LockTimeout(VidlensError):
    errcode = "lock_timeout"

    def __init__(self, message: str = "缓存写锁获取超时"):
        super().__init__(
            message,
            hint="另一个 vidlens 进程正在写同一视频的缓存;等它结束或稍后重试。"
                 "若确认没有并发进程,可删除对应目录下的 .write.lock 后重试。",
            exit_code=1)


def _try_lock(f) -> bool:
    if os.name == "nt":
        import msvcrt
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(f) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextlib.contextmanager
def cache_write_lock(lock_dir, timeout: float = 300.0) -> Iterator[None]:
    """Acquire an exclusive cross-process lock for one cache directory."""
    path = Path(lock_dir)
    path.mkdir(parents=True, exist_ok=True)
    lock_file = path / ".write.lock"
    with open(lock_file, "a+b") as f:
        if f.seek(0, os.SEEK_END) == 0:
            f.write(b"\0")
            f.flush()
        deadline = time.monotonic() + timeout
        acquired = False
        while True:
            if _try_lock(f):
                acquired = True
                break
            if time.monotonic() >= deadline:
                raise LockTimeout()
            time.sleep(0.25)
        try:
            yield
        finally:
            if acquired:
                _unlock(f)
