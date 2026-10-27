import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.core.middleware import SecurityHeadersMiddleware, DemoAuthRateLimitMiddleware, RequestBodyLimitMiddleware
from app.core.security_config import validate_security_settings

from app.api.router import api_router
from app.api.tracking_ws import router as tracking_ws_router
from app.realtime.tracking_manager import tracking_manager
from app.core.config import get_settings
from app.services.organization_context import select_organization, reset_organization

settings = get_settings()
validate_security_settings(settings)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await tracking_manager.start(redis_url=settings.tracking_redis_url,
                                 channel=settings.tracking_redis_channel)
    try:
        yield
    finally:
        await tracking_manager.stop()


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    description="Centralized medical waste management platform API.",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.debug else None,
)

class SessionOriginGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        unsafe = request.method in {'POST','PUT','PATCH','DELETE'}
        cookie = request.cookies.get(settings.auth_cookie_name)
        path = request.url.path
        if unsafe and cookie and path not in {'/api/v1/payments/ipn', '/api/v1/payments/success', '/api/v1/payments/fail', '/api/v1/payments/cancel'}:
            origin = request.headers.get('origin')
            fetch_site = request.headers.get('sec-fetch-site')
            # Browsers supply Origin for credentialed unsafe requests; legacy
            # non-browser API scripts without Fetch headers remain compatible.
            if fetch_site == 'cross-site' or (origin and origin not in settings.cors_origin_list):
                return JSONResponse({'detail':'Unsafe cross-origin session request'}, status_code=403)
        return await call_next(request)

class OrganizationSelectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            token = select_organization(request.headers.get('X-Organization-ID'))
        except ValueError:
            return JSONResponse({'detail': 'Invalid X-Organization-ID'}, status_code=400)
        try:
            return await call_next(request)
        finally:
            reset_organization(token)

app.add_middleware(DemoAuthRateLimitMiddleware)
app.add_middleware(RequestBodyLimitMiddleware, maximum=settings.max_request_body_bytes)
app.add_middleware(OrganizationSelectionMiddleware)
app.add_middleware(SessionOriginGuard)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID", "X-Organization-ID", "X-GPS-Device-ID", "X-GPS-Nonce", "X-GPS-Sent-At", "X-GPS-Signature"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.getLogger("medwaste.errors").error("Unhandled request failure: %s %s", request.method, request.url.path, exc_info=exc)
    # Never leak stack traces or database details through the API.
    if settings.debug:
        # Logging remains intentionally minimal; clients still receive a stable shape.
        pass
    return JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred."})

app.include_router(api_router)
app.include_router(tracking_ws_router)


@app.get("/")
def root():
    return {
        "service": settings.app_name,
        "status": "ok",
        "docs": "/docs",
    }
