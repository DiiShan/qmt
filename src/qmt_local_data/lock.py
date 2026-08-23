from __future__ import annotations

import json
import os
import socket
import time
import uuid
from pathlib import Path

from .errors import LockError
from .models import utc_now


class ProjectLock:
    def __init__(self, data_root: Path, stale_after_seconds: int = 6 * 60 * 60) -> None:
        self.path = data_root / "metadata" / "project.lock"
        self.stale_after_seconds = stale_after_seconds
        self.token = uuid.uuid4().hex
        self.acquired = False

    def acquire(self, break_stale: bool = False) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "token": self.token,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_at": utc_now(),
            "created_epoch": time.time(),
        }
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            existing = self._read_existing()
            age = time.time() - float(existing.get("created_epoch", time.time()))
            if age <= self.stale_after_seconds or not break_stale:
                qualifier = "stale; pass explicit break_stale" if age > self.stale_after_seconds else "active"
                raise LockError(f"Project lock is {qualifier}: {existing}") from exc
            backup = self.path.with_suffix(f".stale.{uuid.uuid4().hex}.json")
            os.replace(self.path, backup)
            return self.acquire(break_stale=False)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        self.acquired = True

    def _read_existing(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"unreadable": True, "created_epoch": self.path.stat().st_mtime}

    def release(self) -> None:
        if not self.acquired or not self.path.exists():
            return
        existing = self._read_existing()
        if existing.get("token") != self.token:
            raise LockError("Refusing to release a lock owned by another process")
        self.path.unlink()
        self.acquired = False

    def __enter__(self) -> "ProjectLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
