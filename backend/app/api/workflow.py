"""One-report entrypoint into existing waste service + queued safe automation."""
import uuid
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy.orm import Session
from app.api.deps import require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.waste import WasteRecordCreate, WasteRecordResponse
from app.services.waste_service import WasteService, HospitalProfileRequiredError, CategoryNotFoundError
from app.services.workflow_orchestrator import enqueue_report

router=APIRouter(prefix='/workflow', tags=['workflow'])

@router.post('/report', status_code=201)
def quick_report(payload:WasteRecordCreate,user:User=Depends(require_roles(UserRole.HOSPITAL)),
                 db:Session=Depends(get_db)):
    try:row=WasteService(db).create_record(user_id=user.id,data=payload)
    except HospitalProfileRequiredError:raise HTTPException(412,'Complete hospital profile')
    except CategoryNotFoundError:raise HTTPException(422,'Valid waste category required')
    except PermissionError:raise HTTPException(403,'Hospital member lacks report permission')
    enqueue_report(db,record_id=row.id,user_id=user.id)
    return {'id':str(row.id),'waste_code':row.waste_code,
            'status':row.status.value,'workflow':'queued',
            'notice':'Your report is queued. Low-confidence or high-risk waste requires staff review.'}


@router.post('/{record_id}/retry')
def retry_reviewed_report(record_id: uuid.UUID,
                          user: User = Depends(require_roles(UserRole.HOSPITAL)),
                          db: Session = Depends(get_db)):
    """Requeue an owned report after human intervention; never override risk gates."""
    from app.services.waste_service import WasteRecordNotFoundError
    try:
        record = WasteService(db).get_record(user_id=user.id, record_id=record_id)
    except (HospitalProfileRequiredError, WasteRecordNotFoundError):
        raise HTTPException(404, 'Report not found')
    try:
        enqueue_report(db, record_id=record.id, user_id=user.id)
    except PermissionError:
        raise HTTPException(403, 'Hospital member lacks report permission')
    return {'id': str(record.id), 'status': record.status.value,
            'workflow': 'retry_requested', 'notice': 'Automated gates are still enforced'}
