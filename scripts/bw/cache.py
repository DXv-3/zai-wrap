"""Small TTL caches for expensive probes."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable


class TTLCache:
    def __init__(self, ttl_sec: float = 300.0) -> None:
        self.ttl = ttl_sec
        self._at = 0.0
        self._val: Any = None
        self._lock = threading.Lock()

    def get(self, loader: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            if self._val is not None and (now - self._at) < self.ttl:
                return self._val
            self._val = loader()
            self._at = now
            return self._val

    def invalidate(self) -> None:
        with self._lock:
            self._val = None
            self._at = 0.0