import time
import uuid
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        started = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=(self)"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; connect-src 'self' http://localhost:8000 http://127.0.0.1:8000 http://localhost:11434 http://127.0.0.1:11434; font-src 'self' data:; frame-ancestors 'none'"
        response.headers["X-Response-Time-ms"] = f"{(time.perf_counter()-started)*1000:.1f}"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


class DemoAuthRateLimitMiddleware(BaseHTTPMiddleware):
    """Shared Redis auth throttling with a bounded single-process local fallback.

    The historical class name is retained for import compatibility. The
    deployment's private reverse proxy establishes request.client securely.
    """
    def __init__(self, app):
        super().__init__(app)
        # A test creates a new ASGI app for each independent test case.  Keep
        # counters and their lock on *this* middleware instance, not the class,
        # so a previous app/test cannot consume the next app's allowance.
        # Repeated requests to one app intentionally share the same counters.
        self._entries: dict[tuple[str, str], list[float]] = {}
        self._lock = Lock()
        from app.core.config import get_settings
        config = get_settings()
        self._redis_url = config.tracking_redis_url
        self._prefix = config.tracking_redis_channel + ":auth:"

    async def dispatch(self, request: Request, call_next) -> Response:
        from starlette.responses import JSONResponse
        if request.method == 'POST' and request.url.path in {
            '/api/v1/auth/login', '/api/v1/auth/register'}:
            now = time.monotonic()
            endpoint = request.url.path.rsplit('/', 1)[-1]
            key = (request.client.host if request.client else 'unknown', endpoint)
            horizon, maximum = (60, 20) if endpoint == 'login' else (3600, 10)
            if self._redis_url:
                from redis.asyncio import Redis
                import hashlib
                redis_key = self._prefix + hashlib.sha256(repr(key).encode()).hexdigest()
                try:
                    async with Redis.from_url(self._redis_url, socket_connect_timeout=2, socket_timeout=2) as client:
                        count = await client.eval(
                            "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",
                            1, redis_key, horizon)
                except Exception:
                    return JSONResponse({'detail':'Authentication service temporarily unavailable.'}, status_code=503)
                if count > maximum:
                    return JSONResponse({'detail':'Too many authentication attempts; try later.'},
                        status_code=429, headers={'Retry-After':str(horizon)})
                return await call_next(request)
            with self._lock:
                # Idle keys expire. Avoid unbounded in-memory growth in demo mode.
                if len(self._entries) > 5000:
                    self._entries = {k:v for k,v in self._entries.items()
                                     if v and now - v[-1] < 3600}
                attempts = [t for t in self._entries.get(key, ()) if now-t < horizon]
                if len(attempts) >= maximum:
                    return JSONResponse({'detail':'Too many authentication attempts; try later.'},
                                        status_code=429, headers={'Retry-After':str(horizon)})
                attempts.append(now)
                self._entries[key] = attempts
        return await call_next(request)


class RequestBodyLimitMiddleware:
    """Bound both declared and chunked bodies before parsers allocate memory."""

    def __init__(self, app, maximum: int):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from starlette.responses import JSONResponse
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid Content-Length"}, 400)(scope, receive, send)
        if length < 0 or length > self.maximum:
            return await JSONResponse({"detail": "Request body is too large"}, 413)(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            size += len(message.get("body", b""))
            if size > self.maximum:
                return await JSONResponse({"detail": "Request body is too large"}, 413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        iterator = iter(messages)

        async def replay():
            return next(iterator, None) or await receive()

        return await self.app(scope, replay, send)

