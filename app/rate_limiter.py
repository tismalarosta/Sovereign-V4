"""
In-memory sliding-window rate limiter — Phase 6.5 SEC-02.

Two limiters:
  chat_limiter    — 10 req/min  — applied to /chat and /propose (expensive LLM calls)
  default_limiter — 60 req/min  — applied to all other protected endpoints

Usage as FastAPI dependency:
    @app.post("/chat", dependencies=[Depends(require_auth), Depends(check_chat_limit)])
"""

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request


class _SlidingWindowLimiter:
    """Thread-safe sliding-window rate limiter keyed by client IP."""

    def __init__(self, calls_per_minute: int) -> None:
        self._limit = calls_per_minute
        self._window = 60.0
        self._lock = threading.Lock()
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        """Raise HTTP 429 if `key` has exceeded the rate limit."""
        now = time.time()
        with self._lock:
            ts = self._buckets[key]
            # Evict timestamps outside the sliding window
            self._buckets[key] = [t for t in ts if now - t < self._window]
            if len(self._buckets[key]) >= self._limit:
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
            self._buckets[key].append(now)


chat_limiter = _SlidingWindowLimiter(calls_per_minute=10)
default_limiter = _SlidingWindowLimiter(calls_per_minute=60)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "127.0.0.1"


def check_chat_limit(request: Request) -> None:
    """FastAPI dependency — enforces chat_limiter (10/min)."""
    chat_limiter.check(_client_ip(request))


def check_default_limit(request: Request) -> None:
    """FastAPI dependency — enforces default_limiter (60/min)."""
    default_limiter.check(_client_ip(request))
