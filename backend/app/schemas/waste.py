import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.waste_enums import WasteStatus, WasteUnit


class WasteCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_recyclable: bool


class WasteRecordCreate(BaseModel):
    category_id: uuid.UUID | None = None
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    unit: WasteUnit
    description: str | None = Field(default=None, max_length=2000)
    generated_at: datetime | None = None


class WasteAttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class WasteRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    waste_code: str
    hospital_id: uuid.UUID
    category: WasteCategoryResponse
    quantity: Decimal
    unit: WasteUnit
    description: str | None
    generated_at: datetime
    status: WasteStatus
    created_at: datetime
    updated_at: datetime
    attachments: list[WasteAttachmentResponse] = []
    received_quantity: Decimal | None = None
    received_at: datetime | None = None
    assigned_facility_id: uuid.UUID | None = None
    assigned_facility_name: str | None = None
    processing_method: str | None = None


class WasteRecordListResponse(BaseModel):
    items: list[WasteRecordResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
