"""Abuse protection for the public demo (and any internet-facing deployment).

- `ClientIPMiddleware`: the client address used for rate limits and the audit trail. Behind proxies the
  left-most X-Forwarded-For entry is whatever the caller typed, so it cannot be trusted. With
  TRUSTED_PROXY_HOPS = n we take the n-th address from the right: the one our own proxy chain (Vercel,
  Render) recorded. 0 = the direct peer (local development).
- `BodySizeLimitMiddleware`: refuses a request body above MAX_REQUEST_BYTES *before* it is read, so a
  multi-gigabyte upload cannot fill the disk or memory (the file checks only run after parsing).
- `heavy_slot()`: at most HEAVY_JOBS_MAX document extractions run at once (OCR needs ~300 MB; the free
  host has 512 MB). Others wait briefly, then get 503 "busy" instead of crashing the server.
- `global_budget()`: site-wide hourly ceilings that no IP spoofing can get around.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager

from fastapi import HTTPException, status

from app.core.config import get_settings


class ClientIPMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        hops = get_settings().trusted_proxy_hops
        if scope["type"] == "http" and hops > 0:
            raw = b",".join(v for k, v in scope.get("headers", []) if k == b"x-forwarded-for").decode("latin-1")
            chain = [h.strip() for h in raw.split(",") if h.strip()]
            if chain:
                ip = chain[-hops] if len(chain) >= hops else chain[0]
                scope = dict(scope, client=(ip, 0))
        await self.app(scope, receive, send)


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = get_settings().max_request_bytes
        for k, v in scope.get("headers", []):
            if k == b"content-length" and v.isdigit() and int(v) > limit:
                return await _reject(send, limit)
        seen = 0

        async def counted():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _TooLarge
            return message

        started = False

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted, tracking_send)
        except _TooLarge:
            if not started:
                await _reject(send, limit)


async def _reject(send, limit: int) -> None:
    body = f'{{"detail":"The request is larger than {limit // (1024 * 1024)} MB."}}'.encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


_heavy: threading.BoundedSemaphore | None = None
_heavy_lock = threading.Lock()


@contextmanager
def heavy_slot(wait_seconds: float = 25.0):
    """Hold one of the HEAVY_JOBS_MAX extraction slots for the duration of the block."""
    global _heavy
    with _heavy_lock:
        if _heavy is None:
            _heavy = threading.BoundedSemaphore(max(1, get_settings().heavy_jobs_max))
    if not _heavy.acquire(timeout=wait_seconds):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Duly is busy reading other invoices right now. Please try again in a minute.")
    try:
        yield
    finally:
        _heavy.release()


_budgets: dict[str, deque[float]] = {}
_budget_lock = threading.Lock()


def global_budget(name: str, per_hour: int) -> None:
    """Count one use of `name` site-wide; 429 once `per_hour` uses happened in the last hour (0 = unlimited)."""
    if per_hour <= 0:
        return
    now = time.time()
    with _budget_lock:
        q = _budgets.setdefault(name, deque())
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= per_hour:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                "This public demo has reached its hourly limit for this action. Please try again later.")
        q.append(now)
