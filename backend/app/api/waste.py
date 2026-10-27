from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.models.waste_enums import WasteStatus
from app.rules.file_upload_rules import UploadValidationError
from app.schemas.waste import (
    WasteAttachmentResponse,
    WasteCategoryResponse,
    WasteRecordCreate,
    WasteRecordListResponse,
    WasteRecordResponse,
)
from app.services.waste_service import (
    CategoryNotFoundError,
    HospitalProfileRequiredError,
    WasteRecordNotFoundError,
    WasteService,
)

router = APIRouter(prefix="/waste", tags=["waste"])

require_hospital = require_roles(UserRole.HOSPITAL)

require_hospital_or_facility = require_roles(
    UserRole.HOSPITAL,
    UserRole.FACILITY,
)



def _profile_required_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_412_PRECONDITION_FAILED,
        detail="Complete your hospital profile before reporting waste.",
    )


@router.get("/categories", response_model=list[WasteCategoryResponse])
def list_categories(
    current_user: User = Depends(require_hospital_or_facility), db: Session = Depends(get_db)
):
    return WasteService(db).list_categories()


@router.post("", response_model=WasteRecordResponse, status_code=status.HTTP_201_CREATED)
def create_waste_record(
    payload: WasteRecordCreate,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return WasteService(db).create_record(user_id=current_user.id, data=payload)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Organization permission denied")
    except HospitalProfileRequiredError:
        raise _profile_required_error()
    except CategoryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown waste category."
        )


@router.get("", response_model=WasteRecordListResponse)
def list_waste_records(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: WasteStatus | None = Query(default=None, alias="status"),
    category_id: UUID | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        items, total = WasteService(db).search_records(
            user_id=current_user.id,
            page=page,
            page_size=page_size,
            status=status_filter,
            category_id=category_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Organization permission denied")
    except HospitalProfileRequiredError:
        raise _profile_required_error()

    total_pages = max(1, (total + page_size - 1) // page_size)
    return WasteRecordListResponse(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{record_id}", response_model=WasteRecordResponse)
def get_waste_record(
    record_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return WasteService(db).get_record(user_id=current_user.id, record_id=record_id)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Organization permission denied")
    except HospitalProfileRequiredError:
        raise _profile_required_error()
    except WasteRecordNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waste record not found.")


@router.get("/{record_id}/processing-report")
def hospital_processing_report(
    record_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    from app.models.processing_record import ProcessingRecord
    try:
        WasteService(db).get_record(user_id=current_user.id, record_id=record_id)
    except (WasteRecordNotFoundError, HospitalProfileRequiredError):
        raise HTTPException(status_code=404, detail="Waste batch not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Organization permission denied")
    item = db.query(ProcessingRecord).filter(ProcessingRecord.waste_record_id == record_id).first()
    if item is None:
        return {"available": False}
    from app.models.audit_log import AuditLog
    demo = db.query(AuditLog.id).filter(
        AuditLog.action == "facility.receipt.demo_manual",
        AuditLog.entity_type == "waste", AuditLog.entity_id == str(record_id)
    ).first() is not None
    return {"simulated": demo,
        "available": True, "processing_method": item.processing_method,
        "status": item.status, "proof_note": item.proof_note,
        "started_at": item.started_at, "proof_submitted_at": item.proof_submitted_at,
        "completed_at": item.completed_at,
    }

@router.post(
    "/{record_id}/attachments",
    response_model=WasteAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    record_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    from app.core.config import get_settings
    limit = min(get_settings().max_request_body_bytes, 10 * 1024 * 1024)
    chunks = []
    total = 0
    while chunk := await file.read(65536):
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail="Attachment exceeds configured upload size limit")
        chunks.append(chunk)
    content = b''.join(chunks)
    try:
        return WasteService(db).add_attachment(
            user_id=current_user.id,
            record_id=record_id,
            filename=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Organization permission denied")
    except HospitalProfileRequiredError:
        raise _profile_required_error()
    except WasteRecordNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waste record not found.")
    except UploadValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{record_id}/attachments/{attachment_id}/download")
def download_attachment(
    record_id: UUID,
    attachment_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        attachment, path = WasteService(db).get_attachment_for_download(
            user_id=current_user.id, record_id=record_id, attachment_id=attachment_id
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Organization permission denied")
    except HospitalProfileRequiredError:
        raise _profile_required_error()
    except WasteRecordNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")

    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File is missing on disk.")

    return FileResponse(
        path=path,
        media_type=attachment.content_type,
        filename=attachment.original_filename,
    )