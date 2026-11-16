"""Middleware for request tracing, structured logging, TTL caching, and rate limiting."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import Flask, Response, g, jsonify, request

logger = logging.getLogger("hydropulse.api")


# ─────────────────────── 1. In-Memory Thread-Safe TTL Cache ─────────────────────────


class InMemoryTTLCache:
    """Thread-safe in-memory cache with time-to-live (TTL) expiration."""

    def __init__(self, default_ttl: int = 60) -> None:
        self.default_ttl = default_ttl
        self._store: dict[str, tuple[Any, int, dict[str, str], float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[Any, int, dict[str, str]] | None:
        now = time.time()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            data, status, headers, expire_at = entry
            if now > expire_at:
                del self._store[key]
                return None
            return data, status, headers

    def set(
        self,
        key: str,
        data: Any,
        status: int = 200,
        headers: dict[str, str] | None = None,
        ttl: int | None = None,
    ) -> None:
        ttl = ttl if ttl is not None else self.default_ttl
        expire_at = time.time() + ttl
        headers = headers or {}
        with self._lock:
            self._store[key] = (data, status, headers, expire_at)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


cache = InMemoryTTLCache(default_ttl=60)


def cached(ttl_seconds: int = 60) -> Callable:
    """Decorator to cache JSON responses of GET endpoints."""

    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Response:
            # Only cache GET requests
            if request.method != "GET":
                return f(*args, **kwargs)

            # Build deterministic cache key from path and sorted query params
            query_items = sorted(request.args.items())
            cache_key = f"{request.path}?{query_items}"

            cached_entry = cache.get(cache_key)
            if cached_entry is not None:
                data, status, headers = cached_entry
                resp = jsonify(data) if not isinstance(data, Response) else data
                resp.status_code = status
                for k, v in headers.items():
                    resp.headers[k] = v
                resp.headers["X-Cache"] = "HIT"
                return resp

            # Execute handler
            result = f(*args, **kwargs)

            # Unpack response
            if isinstance(result, tuple):
                response_obj = result[0]
                status_code = result[1] if len(result) > 1 else 200
            else:
                response_obj = result
                status_code = 200

            # Only cache successful 200 responses
            if status_code == 200:
                if hasattr(response_obj, "get_json"):
                    data_to_cache = response_obj.get_json()
                elif isinstance(response_obj, dict):
                    data_to_cache = response_obj
                else:
                    data_to_cache = None

                if data_to_cache is not None:
                    cache.set(
                        cache_key,
                        data_to_cache,
                        status=status_code,
                        headers={"Content-Type": "application/json"},
                        ttl=ttl_seconds,
                    )

            if isinstance(response_obj, Response):
                response_obj.headers["X-Cache"] = "MISS"
                return response_obj

            resp = jsonify(response_obj)
            resp.status_code = status_code
            resp.headers["X-Cache"] = "MISS"
            return resp

        return wrapper

    return decorator


# ─────────────────────── 2. Sliding Window Rate Limiter ─────────────────────────────


class RateLimiter:
    """Thread-safe sliding-window in-memory rate limiter per IP address."""

    def __init__(self, max_requests: int = 120, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._history: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self.enabled = True

    def is_allowed(self, client_ip: str) -> tuple[bool, int]:
        """Check if client request is within rate limit.

        Returns:
            (is_allowed: bool, retry_after_seconds: int)
        """
        if not self.enabled:
            return True, 0

        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            timestamps = self._history.get(client_ip, [])
            # Prune out-of-window timestamps
            timestamps = [t for t in timestamps if t > window_start]

            if len(timestamps) >= self.max_requests:
                oldest_in_window = timestamps[0]
                retry_after = max(1, int(oldest_in_window + self.window_seconds - now))
                self._history[client_ip] = timestamps
                return False, retry_after

            timestamps.append(now)
            self._history[client_ip] = timestamps
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._history.clear()


limiter = RateLimiter(max_requests=120, window_seconds=60)


# ─────────────────────── 3. Flask Request Hooks ─────────────────────────────────────


def setup_middleware(app: Flask) -> None:
    """Attach request tracking, timing, rate limiting, and structured logging hooks."""

    @app.before_request
    def before_request_hook() -> Response | None:
        # 1. Assign or propagate Request ID
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        g.request_id = req_id
        g.start_time = time.perf_counter()

        # 2. Check rate limit
        client_ip = request.headers.get("X-Forwarded-For") or request.remote_addr or "127.0.0.1"
        client_ip = client_ip.split(",")[0].strip()

        # Skip rate limit on docs or static assets
        if not (request.path.startswith("/docs") or request.path.startswith("/static")):
            allowed, retry_after = limiter.is_allowed(client_ip)
            if not allowed:
                logger.warning(
                    "Rate limit exceeded for %s on %s [Req-ID: %s]", client_ip, request.path, req_id
                )
                from datetime import UTC, datetime

                return (
                    jsonify({
                        "error": {
                            "status_code": 429,
                            "title": "Too Many Requests",
                            "detail": f"Rate limit exceeded. Please retry in {retry_after} seconds.",
                        },
                        "generated_at": datetime.now(UTC).isoformat(),
                        "request_id": req_id,
                    }),
                    429,
                    {"Retry-After": str(retry_after)},
                )
        return None

    @app.after_request
    def after_request_hook(response: Response) -> Response:
        req_id = getattr(g, "request_id", None) or str(uuid.uuid4())
        response.headers["X-Request-ID"] = req_id

        # Calculate latency
        start_time = getattr(g, "start_time", None)
        duration_ms = 0.0
        if start_time is not None:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"

        # Structured access logging
        status = response.status_code
        logger.info(
            "[%s] %s %s -> %d (%.2f ms) [%s]",
            req_id[:8],
            request.method,
            request.path,
            status,
            duration_ms,
            request.remote_addr,
        )
        return response
