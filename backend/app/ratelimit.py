"""Small in-process token-bucket limiter (single-instance MVP deployment)."""
from __future__ import annotations

import threading
import time

from fastapi import Request

from .errors import AppError


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, per_minute: int) -> None:
        if per_minute <= 0:
            return
        now = time.monotonic()
        rate = per_minute / 60.0
        with self._lock:
            tokens, last = self._buckets.get(key, (float(per_minute), now))
            tokens = min(float(per_minute), tokens + (now - last) * rate)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                raise AppError(429, "rate_limited", "Too many requests, please slow down")
            self._buckets[key] = (tokens - 1.0, now)
            if len(self._buckets) > 50_000:  # crude memory bound
                self._buckets.clear()

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
