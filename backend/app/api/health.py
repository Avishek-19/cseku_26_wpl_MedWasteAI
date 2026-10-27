import time
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

_started_at = time.time()


@router.get("/health")
def health():
    """Basic liveness check — does not touch the database."""
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - _started_at, 2),
    }


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    """Readiness check — confirms the API can reach PostgreSQL."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "reachable"}
    except Exception:  # noqa: BLE001 — readiness must fail closed
        # Internal diagnostics belong in access-controlled server logs, never
        # in public readiness responses (which are queried by load balancers).
        logger.exception("Database readiness check failed")
        raise HTTPException(status_code=503, detail={
            "status": "error", "database": "unreachable",
            "message": "Database is unavailable",
        })
