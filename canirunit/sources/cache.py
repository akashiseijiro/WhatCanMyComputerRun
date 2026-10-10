"""Short-lived JSON response cache. Not a database: safe to delete at any time."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class TTLCache:
    def __init__(
        self, directory: Path, ttl_hours: float, clock: Callable[[], float] = time.time
    ) -> None:
        self.directory = directory
        self.ttl_seconds = ttl_hours * 3600
        self._clock = clock

    def _path(self, key: str) -> Path:
        return self.directory / f"{hashlib.sha256(key.encode()).hexdigest()[:40]}.json"

    def get(self, key: str, ttl_hours: float | None = None) -> Any | None:
        ttl = self.ttl_seconds if ttl_hours is None else ttl_hours * 3600
        try:
            entry = json.loads(self._path(key).read_text(encoding="utf-8"))
            if self._clock() - float(entry["t"]) > ttl:
                return None
            return entry["v"]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def set(self, key: str, value: Any) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"t": self._clock(), "k": key, "v": value}, f)
            os.replace(tmp, self._path(key))
        except (OSError, TypeError, ValueError):
            pass  # caching is best-effort

    def clear(self) -> int:
        count = 0
        if self.directory.is_dir():
            for p in self.directory.glob("*.json"):
                try:
                    p.unlink()
                    count += 1
                except OSError:
                    pass
        return count
