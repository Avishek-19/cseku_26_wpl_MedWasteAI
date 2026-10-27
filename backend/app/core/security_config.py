from fastapi import HTTPException, status

from app.core.config import Settings

WEAK_DEV_SECRETS = {
    "dev-only-insecure-secret-change-me",
    "change-me",
    "secret",
}


def validate_security_settings(settings: Settings) -> None:
    """Fail closed for production-like environments with unsafe JWT config."""
    env = settings.environment.lower().strip()
    if settings.payment_mode not in {'disabled','mock','sandbox','live'}:
        raise RuntimeError('Invalid PAYMENT_MODE')
    if env in {'production','prod','staging'} and settings.payment_mode == 'mock':
        raise RuntimeError('Mock payment gateway is forbidden in production/staging')
    if settings.payment_mode == 'live':
        if env not in {'production','prod'} or not settings.payment_live_approved:
            raise RuntimeError('Live payment gateway requires explicit production approval')
        if not settings.payment_public_base_url.startswith('https://'):
            raise RuntimeError('Live merchant callbacks must use HTTPS')
        if not settings.sslcz_store_id or not settings.sslcz_store_password:
            raise RuntimeError('Missing approved payment credentials')
    if env in {"production", "prod", "staging", "demo"}:
        if settings.jwt_secret_key in WEAK_DEV_SECRETS or len(settings.jwt_secret_key) < 32:
            raise RuntimeError("JWT_SECRET_KEY must be a strong secret (32+ characters) outside development.")
        if not settings.auth_cookie_secure:
            raise RuntimeError("AUTH_COOKIE_SECURE must be true outside local HTTP development.")


def require_strong_password(password: str) -> None:
    if len(password) < 10:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Password must be at least 10 characters long.")
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Password is too long.")
    if not any(c.isupper() for c in password) or not any(c.islower() for c in password) or not any(c.isdigit() for c in password):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Password must include uppercase, lowercase, and numeric characters.")
