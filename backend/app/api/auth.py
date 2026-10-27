from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    UpdateAccountRequest,
    UserResponse,
)
from app.services.auth_service import (
    AccountDisabledError,
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    PublicRoleForbiddenError,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _set_session_cookie(response: Response, user: User) -> None:
    token = create_access_token(user_id=user.id, role=user.role.value, auth_version=user.auth_version)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    service = AuthService(db)
    try:
        # Schema already rejects admin; convert public role string to enum.
        from app.models.roles import UserRole as UR
        role_enum = UR(payload.role)
        user = service.register(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            role=role_enum,
        )
    except (PublicRoleForbiddenError, ValueError):
        raise HTTPException(status_code=403, detail="Administrator self-registration is forbidden.")
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    # Registering signs the user in immediately — there's no separate
    # email-verification step, since no external email API is used yet.
    _set_session_cookie(response, user)
    return user


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    service = AuthService(db)
    try:
        user = service.authenticate(email=payload.email, password=payload.password)
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    except AccountDisabledError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been disabled.",
        )

    _set_session_cookie(response, user)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(key=settings.auth_cookie_name, path="/")


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserResponse)
def update_account(
    payload: UpdateAccountRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return AuthService(db).update_account(user=current_user, full_name=payload.full_name)


@router.post("/me/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        AuthService(db).change_password(
            user=current_user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )
    _set_session_cookie(response, current_user)
