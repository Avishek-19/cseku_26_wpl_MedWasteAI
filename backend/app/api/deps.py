import uuid

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import decode_access_token
from app.models.roles import UserRole
from app.models.user import User
from app.repositories.user_repository import UserRepository

settings = get_settings()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(settings.auth_cookie_name)
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated.",
    )
    if not token:
        raise unauthorized

    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized

    user = UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active or payload.get("ver", 0) != user.auth_version:
        raise unauthorized
    return user


def require_roles(*allowed_roles: UserRole):
    """Dependency factory: restricts an endpoint to the given roles.

    Usage: `Depends(require_roles(UserRole.ADMIN))`
    """

    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return user

    return _check
