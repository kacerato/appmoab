import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.responses import JSONResponse

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

RequestHandler = Callable[[Request], Awaitable[Response]]

_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


def _client_id(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_key(request: Request) -> tuple[str, int] | None:
    path = request.url.path
    if path == "/api/auth/login":
        return f"login:{_client_id(request)}", settings.rate_limit_login_requests

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/"):
        return f"mutation:{_client_id(request)}", settings.rate_limit_mutation_requests

    return None


def _rate_limited(request: Request) -> bool:
    if not settings.rate_limit_enabled:
        return False

    bucket_config = _rate_key(request)
    if not bucket_config:
        return False

    key, limit = bucket_config
    now = time.monotonic()
    window_start = now - settings.rate_limit_window_seconds
    bucket = _rate_buckets[key]
    while bucket and bucket[0] < window_start:
        bucket.popleft()

    if len(bucket) >= limit:
        return True

    bucket.append(now)
    return False


def _cache_control(request: Request, response: Response) -> str:
    if request.method != "GET":
        return "no-store"

    path = request.url.path
    if path.startswith("/api/health"):
        return "public, max-age=15"

    if path.startswith("/api/"):
        if response.status_code >= 400:
            return "no-store"
        return f"private, max-age={settings.api_private_cache_seconds}, stale-while-revalidate=60"

    return response.headers.get("Cache-Control", "no-store")


async def performance_and_security_middleware(request: Request, call_next: RequestHandler) -> Response:
    started = time.perf_counter()

    if _rate_limited(request):
        return JSONResponse(
            status_code=429,
            content={"detail": "Muitas requisicoes em pouco tempo. Aguarde alguns segundos e tente novamente."},
            headers={"Retry-After": str(settings.rate_limit_window_seconds)},
        )

    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 1)

    response.headers["X-Response-Time-Ms"] = str(duration_ms)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers["Cache-Control"] = _cache_control(request, response)

    if duration_ms >= settings.performance_log_slow_ms:
        logger.warning(
            "Endpoint lento: %s %s %.1fms status=%s",
            request.method,
            request.url.path,
            duration_ms,
            response.status_code,
        )

    return response
