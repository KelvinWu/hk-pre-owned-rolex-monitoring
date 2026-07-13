from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .errors import RunLocked
from .util import safe_name


class RunLock:
    def __init__(self, lock_dir: Path, monitor_id: str, *, stale_after_seconds: int = 1800) -> None:
        self.lock_dir = lock_dir
        self.path = lock_dir / f"{safe_name(monitor_id)}.lock"
        self.stale_after_seconds = stale_after_seconds
        self.acquired = False

    def __enter__(self) -> "RunLock":
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and time.time() - self.path.stat().st_mtime > self.stale_after_seconds:
            self.path.unlink(missing_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RunLocked(f"Monitor 已有运行锁: {self.path.name}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "created_at": time.time()}, handle)
        self.acquired = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False
