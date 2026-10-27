import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.roles import UserRole

# Only these roles may be chosen during public self-registration.
# ADMIN is never accepted from the public form (also blocked in AuthService).
PublicRegisterRole = Literal["hospital", "collector", "facility"]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=1, max_length=255)
    role: PublicRegisterRole

    @field_validator("role", mode="before")
    @classmethod
    def reject_admin_role(cls, v):
        if v is None:
            return v
        normalized = str(v).strip().lower()
        if normalized == "admin":
            raise ValueError("Administrator self-registration is forbidden.")
        return normalized


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UpdateAccountRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime
