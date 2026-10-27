import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.roles import UserRole
from app.models.waste_enums import IncidentSeverity, IncidentType, RiskLevel


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime


class AdminUserUpdate(BaseModel):
    is_active: bool
    is_verified: bool | None = None


class VerificationItem(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    email: str
    organization_name: str
    registration_number: str
    city: str
    is_verified: bool
    created_at: datetime


class VerificationListResponse(BaseModel):
    items: list[VerificationItem]
    total: int


class CategoryAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_recyclable: bool
    is_active: bool
    created_at: datetime


class CategoryCreate(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    is_recyclable: bool = False


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    is_recyclable: bool | None = None
    is_active: bool | None = None


class RiskRuleAdminResponse(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    category_name: str
    base_risk_level: RiskLevel
    quantity_escalation_threshold: Decimal | None
    is_active: bool
    updated_at: datetime


class RiskRuleUpdate(BaseModel):
    base_risk_level: RiskLevel
    quantity_escalation_threshold: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    is_active: bool = True


class IncidentAdminResponse(BaseModel):
    id: uuid.UUID
    waste_record_id: uuid.UUID
    waste_code: str
    incident_type: IncidentType
    severity: IncidentSeverity
    description: str
    is_resolved: bool
    created_at: datetime


class IncidentResolveRequest(BaseModel):
    is_resolved: bool = True


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_name: str | None
    action: str
    entity_type: str
    entity_id: str | None
    details: dict
    created_at: datetime


class AdminOverviewResponse(BaseModel):
    users_total: int
    active_users: int
    pending_hospitals: int
    pending_collectors: int
    pending_facilities: int
    open_incidents: int
    waste_batches: int
    audit_events: int
