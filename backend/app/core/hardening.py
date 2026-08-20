"""Small, dependency-free production middleware and operational counters."""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("paperlens.api")


def error_body(code: str, message: str, request_id: str) -> dict[str, Any]:
    """Return the stable error envelope while retaining the legacy ``detail`` key."""

    return {"detail": message, "error": {"code": code, "message": message, "request_id": request_id}}


@dataclass
class Metrics:
    """In-process counters suitable for a single API worker and Prometheus scraping."""

    requests: Counter[str] = field(default_factory=Counter)
    durations_ms: list[float] = field(default_factory=list)

    def observe(self, method: str, path: str, status_code: int, duration_ms: float) -> None:
        self.requests["requests_total"] += 1
        self.requests[f"requests_method_total{{method=\"{method}\"}}"] += 1
        self.requests[f"requests_status_total{{status=\"{status_code}\"}}"] += 1
        if path.startswith("/api/papers") and path.endswith("/ingest"):
            self.requests["ingestion_requests_total"] += 1
        if "/chat/" in path:
            self.requests["chat_requests_total"] += 1
        if path.startswith("/api/research/runs"):
            self.requests["research_requests_total"] += 1
        self.durations_ms.append(duration_ms)
        # Keep memory bounded while retaining enough information for local p50/p95 checks.
        if len(self.durations_ms) > 2_000:
            del self.durations_ms[:1_000]

    def prometheus(self) -> str:
        lines = ["# TYPE paperlens_requests_total counter"]
        lines.extend(f"paperlens_{key} {value}" for key, value in sorted(self.requests.items()))
        if self.durations_ms:
            values = sorted(self.durations_ms)
            p50 = values[len(values) // 2]
            p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
            lines.extend(
                [
                    "# TYPE paperlens_request_duration_ms summary",
                    f"paperlens_request_duration_ms{{quantile=\"0.5\"}} {p50:.3f}",
                    f"paperlens_request_duration_ms{{quantile=\"0.95\"}} {p95:.3f}",
                ]
            )
        return "\n".join(lines) + "\n"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Propagate a non-sensitive request ID and emit bounded structured logs."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get("x-request-id", "").strip()
        request_id = supplied[:128] if supplied and _safe_request_id(supplied) else secrets.token_hex(16)
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            metrics = getattr(request.app.state, "metrics", None)
            if metrics is not None:
                metrics.observe(request.method, request.url.path, status_code, duration_ms)
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": status_code,
                        "duration_ms": round(duration_ms, 2),
                    },
                    separators=(",", ":"),
                )
            )
            # BaseHTTPMiddleware gives us the response before finally completes.
            # Header injection is performed by SecurityHeadersMiddleware below.


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add conservative headers to API and artifact responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        is_pdf = request.url.path.endswith("/source")
        if not is_pdf:
            response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if is_pdf:
            origins = " ".join(getattr(request.app.state.settings, "allowed_origins", []))
            response.headers.setdefault("Content-Security-Policy", f"default-src 'none'; frame-ancestors 'self' {origins}")
        else:
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        request_id = getattr(request.state, "request_id", None)
        if request_id:
            response.headers.setdefault("X-Request-ID", request_id)
        return response


class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized JSON requests before FastAPI parses them."""

    def __init__(self, app: Any, *, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        content_type = request.headers.get("content-type", "").lower()
        if content_length and content_type.startswith("application/json"):
            try:
                too_large = int(content_length) > self.max_bytes
            except ValueError:
                too_large = True
            if too_large:
                request_id = getattr(request.state, "request_id", "unknown")
                return JSONResponse(
                    status_code=413,
                    content=error_body("REQUEST_TOO_LARGE", "The request body exceeds the configured limit.", request_id),
                )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Small process-local beta limiter for expensive public operations.

    The limiter is intentionally conservative and bounded. It is a safety net for a
    single API process; an edge/WAF should provide the shared limit when the beta is
    scaled horizontally.
    """

    def __init__(self, app: Any, *, limits: dict[str, int]) -> None:
        super().__init__(app)
        self.limits = {key: max(1, value) for key, value in limits.items()}
        self._windows: dict[tuple[str, str], tuple[float, int]] = {}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        bucket = _rate_bucket(request.url.path, request.method)
        limit = self.limits.get(bucket)
        if limit is None:
            return await call_next(request)
        key = (bucket, _client_key(request))
        now = time.monotonic()
        window_start, count = self._windows.get(key, (now, 0))
        if now - window_start >= 60:
            window_start, count = now, 0
        if count >= limit:
            retry_after = max(1, int(60 - (now - window_start)))
            request_id = getattr(request.state, "request_id", "unknown")
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content=error_body("RATE_LIMITED", "This operation is temporarily rate limited for the beta.", request_id),
            )
        self._windows[key] = (window_start, count + 1)
        # Keep the in-process limiter from becoming an unbounded map.
        if len(self._windows) > 4096:
            self._windows = {entry_key: value for entry_key, value in self._windows.items() if now - value[0] < 60}
        return await call_next(request)


def _safe_request_id(value: str) -> bool:
    return len(value) <= 128 and all(char.isalnum() or char in {"-", "_", "."} for char in value)


def _rate_bucket(path: str, method: str) -> str | None:
    if method == "POST" and path == "/api/papers/ingest":
        return "ingestion"
    if method == "POST" and (path.endswith("/extract") or path.endswith("/verify")):
        return "ai"
    if method == "POST" and "/chat/sessions/" in path and path.endswith("/messages"):
        return "chat"
    if method == "POST" and path == "/api/research/runs":
        return "research"
    return None


def _client_key(request: Request) -> str:
    client = request.client
    return client.host if client and client.host else "unknown"
