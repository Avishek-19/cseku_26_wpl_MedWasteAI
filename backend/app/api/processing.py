from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from app.api.deps import require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.processing import ProcessingProofRequest, ProcessingRecordResponse, ProcessingStartRequest
from app.services.processing_service import (
    FacilityNotAuthorizedError, ProcessingMethodNotAllowedError, ProcessingNotFoundError,
    ProcessingService, ProcessingStateError,
)

router = APIRouter(prefix="/processing", tags=["processing"])
require_facility = require_roles(UserRole.FACILITY)

def _handle(exc: Exception):
    if isinstance(exc, FacilityNotAuthorizedError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This batch is not assigned to your processing facility.")
    if isinstance(exc, ProcessingNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processing record or waste batch not found.")
    if isinstance(exc, ProcessingMethodNotAllowedError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That processing method is not configured for your facility.")
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

@router.get("/{record_id}", response_model=ProcessingRecordResponse | None)
def get_processing(record_id: UUID, current_user: User = Depends(require_facility), db: Session = Depends(get_db)):
    try: return ProcessingService(db).get(current_user.id, record_id)
    except Exception as exc: raise _handle(exc)

@router.post("/{record_id}/start", response_model=ProcessingRecordResponse, status_code=status.HTTP_201_CREATED)
def start_processing(record_id: UUID, payload: ProcessingStartRequest, current_user: User = Depends(require_facility), db: Session = Depends(get_db)):
    try: return ProcessingService(db).start(current_user.id, record_id, payload.processing_method)
    except Exception as exc: raise _handle(exc)

@router.post("/{record_id}/proof", response_model=ProcessingRecordResponse)
def submit_proof(record_id: UUID, payload: ProcessingProofRequest, current_user: User = Depends(require_facility), db: Session = Depends(get_db)):
    try: return ProcessingService(db).submit_proof(current_user.id, record_id, payload.proof_note)
    except Exception as exc: raise _handle(exc)

@router.post("/{record_id}/complete", response_model=ProcessingRecordResponse)
def complete_processing(record_id: UUID, current_user: User = Depends(require_facility), db: Session = Depends(get_db)):
    try: return ProcessingService(db).complete(current_user.id, record_id)
    except Exception as exc: raise _handle(exc)


@router.post("/{record_id}/document", status_code=201)
async def upload_processing_document(record_id: UUID, file: UploadFile = File(...),
                                     current_user: User = Depends(require_facility),
                                     db: Session = Depends(get_db)):
    """Facility-owned processing evidence; accessible to owning hospital as attachment."""
    import uuid
    from pathlib import Path
    from app.core.config import get_settings
    from app.models.waste_attachment import WasteAttachment
    from app.models.waste_enums import WasteEventType, WasteStatus
    from app.models.audit_log import AuditLog
    from app.rules.file_upload_rules import validate_upload, UploadValidationError
    from app.services.waste_event_service import WasteEventService
    from app.services.organization_eligibility import can_profile_action
    from app.repositories.facility_repository import FacilityRepository
    profile = FacilityRepository(db).get_by_user_id(current_user.id)
    if not can_profile_action(db, profile, current_user.id, 'TREATMENT_FACILITY', 'facility_process'):
        raise HTTPException(403, 'Not authorized to submit processing evidence')
    service = ProcessingService(db)
    try:
        item = service.get(current_user.id, record_id)
    except Exception as exc:
        raise _handle(exc)
    if item is None or item.status != 'processing':
        raise HTTPException(409, 'Start processing before uploading a document')
    content = await file.read(10 * 1024 * 1024 + 1)
    mime = file.content_type or ''
    try:
        validate_upload(content_type=mime, size_bytes=len(content))
    except UploadValidationError as exc:
        raise HTTPException(400, str(exc))
    # Validate actual signatures, not just client-declared content type.
    if (mime == 'application/pdf' and not content.startswith(b'%PDF-')) or (
        mime == 'image/png' and not content.startswith(b'\x89PNG\r\n\x1a\n')) or (
        mime == 'image/jpeg' and not content.startswith(b'\xff\xd8\xff')) or (
        mime == 'image/webp' and (content[0:4] != b'RIFF' or content[8:12] != b'WEBP')):
        raise HTTPException(400, 'File content does not match declared type')
    safe_name = Path((file.filename or 'processing-evidence').replace('\\', '/')).name[:180]
    safe_name = ''.join(c for c in safe_name if c.isprintable() and c not in '\\/:') or 'evidence'
    relative = f"waste/{record_id}/processing-proof/{uuid.uuid4().hex}_{safe_name}"
    root = Path(get_settings().local_storage_dir).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(400, 'Invalid storage path')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    try:
        simulated = db.query(AuditLog.id).filter(
            AuditLog.action == "facility.receipt.demo_manual", AuditLog.entity_type == "waste",
            AuditLog.entity_id == str(record_id)).first() is not None
        attachment = WasteAttachment(waste_record_id=record_id, uploaded_by=current_user.id,
            original_filename=safe_name, storage_path=relative,
            content_type=mime, size_bytes=len(content))
        db.add(attachment)
        WasteEventService(db).record(waste_record_id=record_id,
            event_type=WasteEventType.PROCESSING, status_snapshot=WasteStatus.PROCESSING,
            actor_user_id=current_user.id,
            notes=f"{'SIMULATED: ' if simulated else ''}Processing evidence document uploaded: {safe_name}",
            metadata={"document_name": safe_name, "document_id": str(attachment.id), "simulated": simulated}, commit=False)
        db.commit()
        db.refresh(attachment)
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    return {"id": str(attachment.id), "filename": safe_name, "size_bytes": len(content)}