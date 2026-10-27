from app.schemas.audit_reason import meaningful_reason
"""Company onboarding and permission-scoped business and financial endpoints."""
import uuid
from datetime import date, datetime, timezone, timedelta
import hashlib
import secrets
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_roles
from app.core.db import get_db
from app.core.config import get_settings
from app.models.user import User
from app.models.roles import UserRole
from app.models.business import (Organization, OrganizationMember, OrganizationPermit, BillingContract,
    ContractRate, HospitalInvoice, InvoiceLine, InvoiceAdjustment, RecyclingSale, RecyclingSaleLot, RecyclingAllocation, Subscription,
    OperatorJobEvent, OrganizationInvitation, RecyclingReceiptReview)
from app.models.audit_log import AuditLog
from app.models.hospital_profile import HospitalProfile
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.processing_record import ProcessingRecord
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.vehicle import Vehicle
from app.models.waste_record import WasteRecord
from app.models.waste_category import WasteCategory
from app.models.waste_enums import WasteStatus, WasteUnit
from app.services.business_finance import (assert_member, money, issue_invoice,
    record_recycling_distribution, verified_recycling_lot_basis, operator_accepts_new_work,
    recycling_split, bill_due, permits_current)

router=APIRouter(tags=['business'])


def _utc_aware(value: datetime) -> datetime:
    """Normalize DB timestamps; SQLite and some DB drivers return naive UTC datetimes."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def out(model):
    return {col.name: getattr(model, col.name) for col in model.__table__.columns}

def must_be_member(db, user, org_id, roles=None):
    try: return assert_member(db,user,org_id,roles)
    except PermissionError: raise HTTPException(403,'Organization access denied')

class CompanyCreate(BaseModel):
    name: str = Field(min_length=3,max_length=255)
    org_type: str = Field(pattern='^(HOSPITAL|COLLECTION_COMPANY|TREATMENT_FACILITY)$')

@router.post('/organizations',status_code=201)
def create_organization(payload:CompanyCreate, user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    expected={'hospital':'HOSPITAL','collector':'COLLECTION_COMPANY','facility':'TREATMENT_FACILITY'}
    if user.role != UserRole.ADMIN and expected.get(user.role.value)!=payload.org_type:
        raise HTTPException(403,'Role not eligible for this organization type')
    org=Organization(name=payload.name,org_type=payload.org_type,owner_user_id=user.id,status='pending')
    db.add(org);db.flush()
    db.add(OrganizationMember(organization_id=org.id,user_id=user.id,member_role='owner'))
    # Attach an owner's legacy profile only when this is unambiguously their
    # first company of the matching type. Never silently move a linked profile.
    profile_class = {'HOSPITAL': HospitalProfile, 'TREATMENT_FACILITY': TreatmentFacilityProfile}.get(org.org_type)
    if profile_class is not None:
        old_profile = db.scalar(select(profile_class).where(
            profile_class.user_id == user.id, profile_class.organization_id.is_(None)).limit(1))
        other = db.scalar(select(Organization.id).where(
            Organization.owner_user_id == user.id, Organization.org_type == org.org_type,
            Organization.id != org.id).limit(1))
        if old_profile is not None and other is None:
            old_profile.organization_id = org.id
    db.commit();db.refresh(org)
    return out(org)

@router.get('/organizations/mine')
def my_organizations(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return [out(o) for o in db.scalars(select(Organization).join(OrganizationMember,
        OrganizationMember.organization_id == Organization.id).where(
        OrganizationMember.user_id==user.id,OrganizationMember.active.is_(True))).all()]

class PermitCreate(BaseModel):
    permit_type: str = Field(min_length=3,max_length=80)
    reference: str = Field(min_length=3,max_length=255)
    expires_on: date | None = None

@router.post('/organizations/{org_id}/permits')
def add_permit(org_id:uuid.UUID,payload:PermitCreate,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    must_be_member(db,user,org_id,{'owner','manager'})
    permit=OrganizationPermit(organization_id=org_id,**payload.model_dump())
    db.add(permit);db.commit();db.refresh(permit)
    return out(permit)

class VerificationRequest(BaseModel):
    approved: bool
    reason: str = Field(min_length=12,max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_meaningful_reason(cls, value: str) -> str:
        return meaningful_reason(value, minimum=12)

@router.post('/admin/organizations/{org_id}/verification')
def verify_org(org_id:uuid.UUID,payload:VerificationRequest,user:User=Depends(require_roles(UserRole.ADMIN)),db:Session=Depends(get_db)):
    org=db.get(Organization,org_id)
    if not org:raise HTTPException(404,'Organization not found')
    if payload.approved:
        permits=list(db.scalars(select(OrganizationPermit).where(OrganizationPermit.organization_id==org_id)).all())
        if not permits_current(db, org_id, date.today()):
            raise HTTPException(409,'Current independently approved permits required before organization verification')
    org.status='verified' if payload.approved else 'suspended'
    db.add(AuditLog(actor_user_id=user.id,action='organization.verification',entity_type='organization',entity_id=str(org_id),
        details={'approved':payload.approved,'reason':payload.reason}))
    db.commit()
    return out(org)

@router.post('/admin/permits/{permit_id}/review')
def review_permit(permit_id:uuid.UUID,payload:VerificationRequest,
                  user:User=Depends(require_roles(UserRole.ADMIN)),db:Session=Depends(get_db)):
    permit=db.get(OrganizationPermit,permit_id)
    if not permit:raise HTTPException(404,'Permit not found')
    if payload.approved and permit.expires_on is not None and permit.expires_on <= date.today():
        raise HTTPException(409,'Expired permit cannot be approved')
    permit.approval_status='approved' if payload.approved else 'rejected'
    permit.approved_by=user.id
    permit.approved_at=datetime.now(timezone.utc)
    db.add(AuditLog(actor_user_id=user.id,action='organization.permit.review',
        entity_type='organization_permit',entity_id=str(permit_id),
        details={'approved':payload.approved,'reason':payload.reason}))
    db.commit()
    return out(permit)

class OrganizationMemberAdd(BaseModel):
    user_id: uuid.UUID
    member_role: str = Field(pattern='^(manager|dispatcher|driver|finance|worker)$')

@router.get('/organizations/{org_id}/members')
def company_members(org_id:uuid.UUID,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    must_be_member(db,user,org_id)
    members = list(db.scalars(select(OrganizationMember).where(
        OrganizationMember.organization_id==org_id,
        OrganizationMember.active.is_(True))).all())
    result = []
    for member in members:
        account = db.get(User, member.user_id)
        result.append({**out(member), "user_name": account.full_name if account else "Unknown user",
                       "user_email": account.email if account else "", "user_active": bool(account and account.is_active)})
    return result

@router.post('/organizations/{org_id}/members', status_code=201)
def add_company_member(org_id:uuid.UUID,payload:OrganizationMemberAdd,
                       user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    org=must_be_member(db,user,org_id,{'owner','manager'})
    # Membership management must not let a company manager promote peers.
    actor_member=db.scalar(select(OrganizationMember).where(
        OrganizationMember.organization_id==org_id,
        OrganizationMember.user_id==user.id,OrganizationMember.active.is_(True)))
    if user.role!=UserRole.ADMIN and payload.member_role=='manager' and (
        actor_member is None or actor_member.member_role!='owner'):
        raise HTTPException(403,'Only the organization owner may appoint managers')
    target=db.get(User,payload.user_id)
    valid_role={'COLLECTION_COMPANY':UserRole.COLLECTOR,
                'TREATMENT_FACILITY':UserRole.FACILITY,
                'HOSPITAL':UserRole.HOSPITAL}.get(org.org_type)
    if not target or not target.is_active or target.role!=valid_role:
        raise HTTPException(409,'Active, matching-role member required')
    existing=db.scalar(select(OrganizationMember).where(
        OrganizationMember.organization_id==org_id,OrganizationMember.user_id==target.id))
    if existing:
        raise HTTPException(409,'Member already exists or requires admin reactivation')
    member=OrganizationMember(organization_id=org_id,user_id=target.id,member_role=payload.member_role)
    db.add(member)
    db.add(AuditLog(actor_user_id=user.id,action='organization.member.add',entity_type='organization',
        entity_id=str(org_id),details={'member_id':str(target.id),'role':payload.member_role}))
    db.commit();db.refresh(member)
    return out(member)

@router.get('/organizations/{org_id}/subscriptions')
def list_subscriptions(org_id:uuid.UUID,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    org=must_be_member(db,user,org_id,{'owner','manager','finance'})
    if org.org_type not in {'COLLECTION_COMPANY','TREATMENT_FACILITY'}:
        raise HTTPException(409,'Not an operator organization')
    return [out(s) for s in db.scalars(select(Subscription).where(
        Subscription.organization_id==org_id).order_by(Subscription.period_start.desc()).limit(50)).all()]

@router.get('/organizations/{org_id}/eligibility')
def eligibility(org_id:uuid.UUID,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    org=must_be_member(db,user,org_id)
    count=db.scalar(select(func.count()).select_from(OperatorJobEvent).where(
        OperatorJobEvent.organization_id==org_id,OperatorJobEvent.reversed_at.is_(None))) or 0
    return {'verified':org.status=='verified','eligible_completed_jobs':count,
            'free_jobs_left':max(0,5-count),'can_accept_new_work':operator_accepts_new_work(db,org_id,date.today())}

class ContractCreate(BaseModel):
    hospital_org_id: uuid.UUID
    billing_anchor_local: date
    due_days: int = Field(default=15,ge=1,le=90)

@router.post('/admin/contracts', status_code=201)
def new_contract(payload:ContractCreate,user:User=Depends(require_roles(UserRole.ADMIN)),db:Session=Depends(get_db)):
    org=db.get(Organization,payload.hospital_org_id)
    if not org or org.org_type!='HOSPITAL':raise HTTPException(422,'Hospital organization required')
    if db.scalar(select(BillingContract.id).where(BillingContract.hospital_org_id == org.id,
                                               BillingContract.active.is_(True)).limit(1)):
        raise HTTPException(409,'An active billing contract already exists for this hospital')
    row=BillingContract(**payload.model_dump(),cycle_days=15)
    db.add(row);db.commit();db.refresh(row)
    return out(row)

class RateCreate(BaseModel):
    category_id:uuid.UUID
    collection_rate: Decimal=Field(ge=0,decimal_places=2)
    treatment_rate: Decimal=Field(ge=0,decimal_places=2)
    platform_rate: Decimal=Field(ge=0,decimal_places=2)
    effective_from:date

@router.post('/admin/contracts/{contract_id}/rates',status_code=201)
def add_rate(contract_id:uuid.UUID,payload:RateCreate,user:User=Depends(require_roles(UserRole.ADMIN)),db:Session=Depends(get_db)):
    if not db.get(BillingContract,contract_id):raise HTTPException(404,'Contract not found')
    category = db.get(WasteCategory, payload.category_id)
    if not category or not category.is_active or category.code == 'PENDING':
        raise HTTPException(422, 'Select an active classified waste category')
    row=ContractRate(contract_id=contract_id,**payload.model_dump())
    db.add(row)
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, 'A rate already exists for this category and effective date')
    db.refresh(row)
    return out(row)

@router.post('/admin/contracts/{contract_id}/invoices/{cycle_number}')
def create_cycle_invoice(contract_id:uuid.UUID,cycle_number:int,user:User=Depends(require_roles(UserRole.ADMIN)),db:Session=Depends(get_db)):
    contract=db.get(BillingContract,contract_id)
    if contract is None:raise HTTPException(404,'Contract not found')
    try:row=issue_invoice(db,contract,cycle_number,actor_user_id=user.id)
    except ValueError as exc:raise HTTPException(409,str(exc))
    return out(row)

@router.get('/invoices')
def list_invoices(org_id:uuid.UUID,page:int=Query(1,ge=1),user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    must_be_member(db,user,org_id,{'owner','manager','finance'})
    return [out(i) for i in db.scalars(select(HospitalInvoice).where(
        HospitalInvoice.hospital_org_id==org_id).order_by(HospitalInvoice.issued_at.desc()).offset((page-1)*25).limit(25)).all()]

@router.get('/invoices/{invoice_id}')
def invoice_detail(invoice_id:uuid.UUID,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    invoice=db.get(HospitalInvoice,invoice_id)
    if not invoice:raise HTTPException(404,'Invoice not found')
    must_be_member(db,user,invoice.hospital_org_id,{'owner','manager','finance'})
    return {**out(invoice),
        'lines':[out(x) for x in db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id==invoice.id)).all()],
        'adjustments':[out(x) for x in db.scalars(select(InvoiceAdjustment).where(
            InvoiceAdjustment.invoice_id==invoice.id).order_by(InvoiceAdjustment.created_at)).all()]}

class RecyclingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facility_org_id:uuid.UUID
    source_reference:str=Field(min_length=4,max_length=120)
    clearance_reference:str=Field(min_length=4,max_length=120)
    buyer_invoice_ref:str=Field(min_length=4,max_length=120)
    proceeds_bdt:Decimal=Field(ge=0,decimal_places=2)
    approved_costs_bdt:Decimal=Field(ge=0,decimal_places=2)
    waste_record_ids:list[uuid.UUID]=Field(min_length=1,max_length=100)

@router.post('/recycling/sales')
def record_sale(payload:RecyclingCreate,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    # Admin can assemble demo sales through the dedicated Finance workflow;
    # facility users still need their own active organization membership.
    if user.role == UserRole.ADMIN:
        org = db.get(Organization, payload.facility_org_id)
    else:
        org = must_be_member(db, user, payload.facility_org_id, {'owner','manager','finance'})
    if org is None or org.org_type!='TREATMENT_FACILITY' or org.status!='verified':
        raise HTTPException(403,'Verified facility required')
    if len(set(payload.waste_record_ids)) != len(payload.waste_record_ids):
        raise HTTPException(422, 'Duplicate waste batch IDs are not allowed')
    row=RecyclingSale(**payload.model_dump(exclude={'waste_record_ids'}),sale_payment_verified=False)
    # Lock and validate before the sale is committed. Unique waste_record_id
    # protects against concurrent double allocation across different sales.
    try:
        weights=verified_recycling_lot_basis(db,row,lot_ids=payload.waste_record_ids)
        db.add(row);db.flush()
        for record_id in payload.waste_record_ids:
            record=db.get(WasteRecord,record_id)
            hospital=db.get(HospitalProfile,record.hospital_id)
            db.add(RecyclingSaleLot(sale_id=row.id,waste_record_id=record_id,
                hospital_org_id=hospital.organization_id,
                contribution_kg=Decimal(str(record.received_quantity))))
        db.add(AuditLog(actor_user_id=user.id, action='recycling.sale.created',
            entity_type='recycling_sale', entity_id=str(row.id), details={
                'facility_org_id': str(row.facility_org_id),
                'batch_ids': [str(ident) for ident in payload.waste_record_ids],
                'created_by_admin': user.role == UserRole.ADMIN,
            }))
        db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'A waste batch is already assigned to a recycling sale')
    except ValueError as exc:
        db.rollback();raise HTTPException(409,str(exc))
    db.refresh(row)
    return {**out(row),'verified_hospital_contribution_kg':{str(k):str(v) for k,v in weights.items()}}

# Admin Finance UI endpoints. The server generates candidate lists from verified
# processing evidence; these are advisory. The sale POST always revalidates
# rows under lock and the unique lot constraint prevents double allocation.
@router.get('/admin/recycling/eligible-batches')
def admin_recycling_eligible_batches(
    facility_org_id: uuid.UUID,
    user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, facility_org_id)
    profile = db.scalar(select(TreatmentFacilityProfile).where(
        TreatmentFacilityProfile.organization_id == facility_org_id).limit(1))
    if not org or org.org_type != 'TREATMENT_FACILITY' or org.status != 'verified' or not profile or not profile.is_verified:
        raise HTTPException(409, 'Verified facility and facility profile required')
    rows = db.execute(select(WasteRecord, HospitalProfile, WasteCategory, ProcessingRecord)
        .join(HospitalProfile, HospitalProfile.id == WasteRecord.hospital_id)
        .join(WasteCategory, WasteCategory.id == WasteRecord.category_id)
        .join(ProcessingRecord, ProcessingRecord.waste_record_id == WasteRecord.id)
        .outerjoin(RecyclingSaleLot, RecyclingSaleLot.waste_record_id == WasteRecord.id)
        .where(ProcessingRecord.facility_id == profile.id,
               ProcessingRecord.completed_at.is_not(None),
               WasteRecord.status == WasteStatus.COMPLETED,
               WasteRecord.unit == WasteUnit.KG,
               WasteRecord.received_quantity > 0,
               HospitalProfile.organization_id.is_not(None),
               WasteCategory.is_recyclable.is_(True),
               RecyclingSaleLot.id.is_(None))
        .order_by(ProcessingRecord.completed_at.desc()).limit(100)).all()
    return [{
        'id': str(record.id), 'waste_code': record.waste_code,
        'hospital_org_id': str(hospital.organization_id), 'hospital_name': hospital.name,
        'received_kg': str(record.received_quantity), 'category': category.name,
        'processed_at': proof.completed_at.isoformat(),
    } for record, hospital, category, proof in rows
        if proof.processing_method.upper() in {'RECYCLING','MATERIAL_RECOVERY'}]


@router.get('/admin/recycling/sales')
def admin_recycling_sales(
    user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    sales = list(db.scalars(select(RecyclingSale)
        .order_by(RecyclingSale.created_at.desc()).limit(100)).all())
    if not sales:
        return []
    ids = [row.id for row in sales]
    lots = list(db.scalars(select(RecyclingSaleLot)
        .where(RecyclingSaleLot.sale_id.in_(ids))).all())
    allocations = list(db.scalars(select(RecyclingAllocation)
        .where(RecyclingAllocation.sale_id.in_(ids))).all())
    audit_events = list(db.scalars(select(AuditLog)
        .where(AuditLog.entity_type == 'recycling_sale',
               AuditLog.entity_id.in_([str(sale_id) for sale_id in ids]))
        .order_by(AuditLog.created_at.desc()).limit(500)).all())
    reviews = {r.sale_id: r for r in db.scalars(select(RecyclingReceiptReview).where(RecyclingReceiptReview.sale_id.in_(ids))).all()}
    return [{**out(sale),
        'receipt_review': out(reviews[sale.id]) if sale.id in reviews else None,
        'lots': [out(lot) for lot in lots if lot.sale_id == sale.id],
        'allocations': [out(a) for a in allocations if a.sale_id == sale.id],
        'audit_history': [
            {'action': event.action, 'actor_user_id': str(event.actor_user_id) if event.actor_user_id else None,
             'created_at': event.created_at.isoformat()}
            for event in audit_events if event.entity_id == str(sale.id)],
    } for sale in sales]


@router.post('/admin/recycling/sales', status_code=201)
def admin_record_recycling_sale(
    payload: RecyclingCreate,
    user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    return record_sale(payload, user, db)


class ReceiptEvidenceCreate(BaseModel):
    bank_reference: str = Field(min_length=8, max_length=120)
    received_bdt: Decimal = Field(gt=0, decimal_places=2)
    received_on: date
    evidence_note: str = Field(min_length=20, max_length=2000)


@router.post('/admin/recycling/sales/{sale_id}/receipt-evidence', status_code=201)
def submit_recycling_receipt(sale_id: uuid.UUID, payload: ReceiptEvidenceCreate,
    user: User = Depends(require_roles(UserRole.ADMIN)), db: Session = Depends(get_db)):
    sale = db.scalar(select(RecyclingSale).where(RecyclingSale.id == sale_id).with_for_update(of=RecyclingSale))
    if not sale or sale.sale_payment_verified:
        raise HTTPException(409, 'An unallocated recycling sale is required')
    if money(payload.received_bdt) != money(sale.proceeds_bdt):
        raise HTTPException(422, 'Bank receipt amount must equal recorded sale proceeds')
    if payload.received_on > datetime.now(timezone.utc).date():
        raise HTTPException(422, 'Receipt date cannot be in the future')
    if db.scalar(select(RecyclingReceiptReview.id).where(RecyclingReceiptReview.sale_id == sale_id)):
        raise HTTPException(409, 'Bank evidence is already awaiting review')
    row = RecyclingReceiptReview(sale_id=sale_id, submitted_by=user.id, **payload.model_dump())
    db.add(row)
    db.add(AuditLog(actor_user_id=user.id, action='recycling.receipt.evidence_submitted',
        entity_type='recycling_sale', entity_id=str(sale_id), details={
            'bank_reference': payload.bank_reference, 'received_bdt': str(payload.received_bdt)}))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'This bank reference or sale already has receipt evidence')
    db.refresh(row)
    return out(row)


class VerifySale(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bank_receipt_reference:str=Field(min_length=8,max_length=120)

@router.post('/admin/recycling/sales/{sale_id}/confirm-receipt')
def confirm_recycling_sale(sale_id:uuid.UUID,payload:VerifySale,user:User=Depends(require_roles(UserRole.ADMIN)),db:Session=Depends(get_db)):
    sale=db.scalar(select(RecyclingSale).where(RecyclingSale.id == sale_id).with_for_update(of=RecyclingSale))
    if not sale:raise HTTPException(404,'Sale not found')
    if sale.sale_payment_verified:raise HTTPException(409,'Receipt already verified')
    review = db.scalar(select(RecyclingReceiptReview).where(
        RecyclingReceiptReview.sale_id == sale_id).with_for_update(of=RecyclingReceiptReview))
    if review is not None:
        if review.submitted_by == user.id:
            raise HTTPException(403, 'A different administrator must independently approve this receipt')
        if review.bank_reference != payload.bank_receipt_reference or money(review.received_bdt) != money(sale.proceeds_bdt):
            raise HTTPException(409, 'Receipt evidence does not match the sale proceeds')
        review.state = 'approved'
        review.approved_by = user.id
        review.reviewed_at = datetime.now(timezone.utc)
    elif get_settings().environment.lower() != 'test':
        raise HTTPException(409, 'Submit bank receipt evidence for independent review first')
    # Revalidate every immutable lot before recording sale approval.
    try:
        weights=verified_recycling_lot_basis(db,sale)
    except ValueError as exc:
        db.rollback();raise HTTPException(409,str(exc))
    sale.approved_by=user.id
    sale.sale_payment_verified=True
    db.add(AuditLog(actor_user_id=user.id,action='recycling.sale.receipt_attested',entity_type='recycling_sale',
        entity_id=str(sale.id),details={'bank_receipt_reference':payload.bank_receipt_reference,
        'allocation_method':'verified_received_batch_kg',
        'verified_lot_count':len(db.scalars(select(RecyclingSaleLot).where(RecyclingSaleLot.sale_id==sale.id)).all())}))
    try:result=record_recycling_distribution(db,sale)
    except (ValueError,PermissionError) as exc:db.rollback();raise HTTPException(409,str(exc))
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Recycling sale is already allocated')
    return {'net_profit_bdt':recycling_split(sale.proceeds_bdt,sale.approved_costs_bdt)[0],
            'verified_input_weights_kg': {str(key): str(value) for key,value in weights.items()},
            'allocations':[out(x) for x in result]}

class MonthlySubscriptionCreate(BaseModel):
    organization_id:uuid.UUID
    period_start:date
    period_end:date
    agreed_price_bdt:Decimal=Field(gt=0,decimal_places=2)

@router.post('/admin/subscriptions',status_code=201)
def new_subscription(payload:MonthlySubscriptionCreate,user:User=Depends(require_roles(UserRole.ADMIN)),db:Session=Depends(get_db)):
    org=db.get(Organization,payload.organization_id)
    if not org or org.org_type not in {'COLLECTION_COMPANY','TREATMENT_FACILITY'} or org.status!='verified':
        raise HTTPException(409,'Verified eligible operator required')
    if payload.period_start >= payload.period_end or (payload.period_end-payload.period_start).days>31:
        raise HTTPException(422,'Invalid subscription period')
    row=Subscription(organization_id=payload.organization_id,period_start=payload.period_start,
                     period_end=payload.period_end,price_bdt=money(payload.agreed_price_bdt),state='unpaid')
    db.add(row);db.commit();db.refresh(row)
    return out(row)



class FacilityReceiptExceptionApprove(BaseModel):
    reason: str = Field(min_length=20, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_meaningful_reason(cls, value: str) -> str:
        return meaningful_reason(value, minimum=20)

@router.post('/admin/waste/{record_id}/receipt-exception')
def approve_facility_receipt_exception(record_id: uuid.UUID, payload: FacilityReceiptExceptionApprove,
    user: User = Depends(require_roles(UserRole.ADMIN)), db: Session = Depends(get_db)):
    """Last-resort auditable emergency approval, not a normal delivery shortcut."""
    from app.models.waste_record import WasteRecord
    from app.models.matching_record import MatchingRecord
    from app.models.waste_enums import WasteStatus
    row = db.get(WasteRecord, record_id)
    match = db.scalar(select(MatchingRecord).where(
        MatchingRecord.waste_record_id == record_id,
        MatchingRecord.is_confirmed.is_(True)).limit(1))
    if not row or row.status != WasteStatus.IN_TRANSIT or not match or not match.confirmed_facility_id:
        raise HTTPException(409, 'Only a confirmed in-transit batch can receive a manual arrival exception')
    approval = AuditLog(actor_user_id=user.id, action='facility.receipt.exception_approved',
        entity_type='waste', entity_id=str(record_id), details={
        'facility_id': str(match.confirmed_facility_id), 'reason': payload.reason.strip()})
    db.add(approval); db.commit()
    return {'approved': True, 'record_id': str(record_id), 'expires_in_seconds': 1200}

# --- Organization invitations (secure member onboarding) ---
ALLOWED_MEMBER_ROLES = {"owner", "manager", "dispatcher", "driver", "finance", "worker"}

class InviteCreate(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    member_role: str = Field(pattern="^(owner|manager|dispatcher|driver|finance|worker)$")

@router.post("/organizations/{org_id}/invitations", status_code=201)
def invite_member(
    org_id: uuid.UUID,
    payload: InviteCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Owner/manager can invite a user by email. Token is single-use and time-limited."""
    must_be_member(db, user, org_id, roles={"owner", "manager"})
    actor_member = db.scalar(select(OrganizationMember).where(
        OrganizationMember.organization_id == org_id,
        OrganizationMember.user_id == user.id, OrganizationMember.active.is_(True)))
    if payload.member_role == "owner":
        raise HTTPException(403, "Owner transfer requires a separate verified process")
    if payload.member_role == "manager" and user.role != UserRole.ADMIN and (
        actor_member is None or actor_member.member_role != "owner"):
        raise HTTPException(403, "Only the owner may invite managers")
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "Organization not found")
    if org.status == "suspended":
        raise HTTPException(409, "Organization is suspended")
    email = payload.email.strip().lower()
    # Existing revoked/expired/accepted invites occupy the historical unique
    # org/email key; safely rotate rather than attempting a duplicate INSERT.
    existing = db.scalar(select(OrganizationInvitation).where(
        OrganizationInvitation.organization_id == org_id,
        OrganizationInvitation.email == email).with_for_update(of=OrganizationInvitation))
    if existing is not None and existing.status == 'pending' and _utc_aware(existing.expires_at) > datetime.now(timezone.utc):
        raise HTTPException(409, "Pending invitation already exists for this email")
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    inv = existing or OrganizationInvitation(organization_id=org_id, email=email)
    inv.member_role = payload.member_role
    inv.token = digest  # only a hash is ever stored in the database
    inv.invited_by = user.id
    inv.status = 'pending'
    inv.accepted_at = None
    inv.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    db.add(inv)
    db.add(AuditLog(
        actor_user_id=user.id,
        action="organization.invitation.created",
        entity_type="organization",
        entity_id=str(org_id),
        details={"email": email, "member_role": payload.member_role},
    ))
    db.commit()
    db.refresh(inv)
    # Token returned only to the inviter (email delivery is out of band / future).
    response = out(inv)
    response['token'] = token  # one-time delivery only, never stored in plaintext
    return response


@router.get("/organizations/{org_id}/invitations")
def list_invitations(
    org_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    must_be_member(db, user, org_id, roles={"owner", "manager"})
    rows = list(db.scalars(
        select(OrganizationInvitation).where(OrganizationInvitation.organization_id == org_id)
        .order_by(OrganizationInvitation.created_at.desc())
    ).all())
    # Never expose raw tokens in list view
    result = []
    for r in rows:
        d = out(r)
        d.pop("token", None)
        result.append(d)
    return result


@router.post("/invitations/accept", status_code=200)
def accept_invitation(
    token: str = Query(..., min_length=16, max_length=128),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Authenticated user accepts an invitation addressed to their email."""
    inv = db.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.token == hashlib.sha256(token.encode()).hexdigest(),
            OrganizationInvitation.status == "pending",
        )
    )
    if inv is None:
        raise HTTPException(404, "Invitation not found or already used")
    if inv.member_role == "owner":
        raise HTTPException(403, "Owner transfer requires independent verification")
    if _utc_aware(inv.expires_at) < datetime.now(timezone.utc):
        inv.status = "expired"
        db.commit()
        raise HTTPException(410, "Invitation has expired")
    if user.email.strip().lower() != inv.email.strip().lower():
        raise HTTPException(403, "Invitation is addressed to a different email")
    org = db.get(Organization, inv.organization_id)
    expected_role = {
        "HOSPITAL": UserRole.HOSPITAL,
        "COLLECTION_COMPANY": UserRole.COLLECTOR,
        "TREATMENT_FACILITY": UserRole.FACILITY,
    }.get(org.org_type if org else None)
    if org is None or org.status == "suspended" or expected_role is None or user.role != expected_role:
        raise HTTPException(403, "User role or organization status is not eligible for this invitation")
    existing = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == inv.organization_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if existing is not None:
        existing.active = True
        existing.member_role = inv.member_role
        member = existing
    else:
        member = OrganizationMember(
            organization_id=inv.organization_id,
            user_id=user.id,
            member_role=inv.member_role,
            active=True,
        )
        db.add(member)
    inv.status = "accepted"
    inv.accepted_at = datetime.now(timezone.utc)
    db.add(AuditLog(
        actor_user_id=user.id,
        action="organization.invitation.accepted",
        entity_type="organization",
        entity_id=str(inv.organization_id),
        details={"member_role": inv.member_role},
    ))
    db.commit()
    db.refresh(member)
    return out(member)


@router.post("/organizations/{org_id}/invitations/{invite_id}/revoke", status_code=200)
def revoke_invitation(
    org_id: uuid.UUID,
    invite_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    must_be_member(db, user, org_id, roles={"owner", "manager"})
    inv = db.get(OrganizationInvitation, invite_id)
    if inv is None or inv.organization_id != org_id:
        raise HTTPException(404, "Invitation not found")
    if inv.status != "pending":
        raise HTTPException(409, f"Invitation is already {inv.status}")
    inv.status = "revoked"
    db.add(AuditLog(
        actor_user_id=user.id,
        action="organization.invitation.revoked",
        entity_type="organization",
        entity_id=str(org_id),
        details={"invite_id": str(invite_id)},
    ))
    db.commit()
    return {"status": "revoked", "id": str(invite_id)}



# ----- Governance workspace APIs: same eligibility rules as dispatch -----
@router.get('/admin/organizations')
def admin_organizations(status: str | None = None,
                        user: User = Depends(require_roles(UserRole.ADMIN)),
                        db: Session = Depends(get_db)):
    stmt = select(Organization).order_by(Organization.created_at.desc()).limit(300)
    if status in {'pending','verified','suspended'}:
        stmt = select(Organization).where(Organization.status == status).order_by(Organization.created_at.desc()).limit(300)
    return [out(o) for o in db.scalars(stmt).all()]

@router.get('/admin/permits')
def admin_permits(organization_id: uuid.UUID | None = None,
                  user: User = Depends(require_roles(UserRole.ADMIN)),
                  db: Session = Depends(get_db)):
    stmt = select(OrganizationPermit).order_by(OrganizationPermit.id.desc()).limit(500)
    if organization_id:
        stmt = select(OrganizationPermit).where(
            OrganizationPermit.organization_id == organization_id).order_by(OrganizationPermit.id.desc()).limit(500)
    return [out(p) for p in db.scalars(stmt).all()]

@router.get('/organizations/{org_id}/permits')
def organization_permits(org_id: uuid.UUID, user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    must_be_member(db, user, org_id)
    return [out(p) for p in db.scalars(select(OrganizationPermit).where(
        OrganizationPermit.organization_id == org_id).order_by(OrganizationPermit.id.desc())).all()]

@router.get('/admin/contracts')
def admin_contracts(user: User = Depends(require_roles(UserRole.ADMIN)),
                    db: Session = Depends(get_db)):
    return [out(c) for c in db.scalars(select(BillingContract).order_by(
        BillingContract.created_at.desc()).limit(250)).all()]

@router.get('/admin/contracts/{contract_id}/rates')
def admin_contract_rates(contract_id: uuid.UUID,
                         user: User = Depends(require_roles(UserRole.ADMIN)),
                         db: Session = Depends(get_db)):
    if db.get(BillingContract, contract_id) is None:
        raise HTTPException(404,'Contract not found')
    return [out(r) for r in db.scalars(select(ContractRate).where(
        ContractRate.contract_id == contract_id).order_by(ContractRate.effective_from.desc())).all()]

@router.get('/admin/invoices')
def admin_invoices(user: User = Depends(require_roles(UserRole.ADMIN)),
                   db: Session = Depends(get_db)):
    return [out(i) for i in db.scalars(select(HospitalInvoice).order_by(
        HospitalInvoice.issued_at.desc()).limit(200)).all()]


@router.post('/organizations/{org_id}/link-existing-profile')
def link_existing_profile(org_id:uuid.UUID, user:User=Depends(get_current_user),
                          db:Session=Depends(get_db)):
    """Explicitly link a legacy unscoped profile without changing its owner.

    A profile already belonging to another company is NEVER silently moved.
    """
    org=must_be_member(db,user,org_id,{'owner'})
    profile_type={'HOSPITAL':HospitalProfile,'TREATMENT_FACILITY':TreatmentFacilityProfile}.get(org.org_type)
    if profile_type is None:
        raise HTTPException(409,'Only hospital and facility profiles can be linked')
    profile=db.scalar(select(profile_type).where(profile_type.user_id==user.id).limit(1))
    if profile is None:
        raise HTTPException(404,'Create a role profile before linking')
    if profile.organization_id == org.id:
        return {'linked':True,'organization_id':str(org.id)}
    if profile.organization_id is not None:
        raise HTTPException(409,'Existing profile already belongs to another organization')
    conflict=db.scalar(select(profile_type.id).where(
        profile_type.organization_id==org.id).limit(1))
    if conflict is not None:
        raise HTTPException(409,'Organization already has a profile')
    profile.organization_id=org.id
    db.add(AuditLog(actor_user_id=user.id, action='organization.profile.linked',
        entity_type='organization', entity_id=str(org.id),
        details={'profile_id':str(profile.id),'profile_type':org.org_type}))
    db.commit()
    return {'linked':True,'organization_id':str(org.id)}


@router.get('/organizations/{org_id}/earnings')
def operator_earnings(org_id: uuid.UUID, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Accrued service earnings from issued invoices, not a claim of cash payouts.

    Collection attribution uses the vehicle's company; treatment uses the
    processing facility that actually completed the batch. Records without
    auditable attribution are excluded, never guessed.
    """
    org = must_be_member(db, user, org_id, {'owner', 'manager', 'finance'})
    if org.org_type not in {'COLLECTION_COMPANY', 'TREATMENT_FACILITY'}:
        raise HTTPException(409, 'Only operator organizations have earnings')
    # Every invoice line is counted at most once per organization; SQL EXISTS
    # subqueries prevent duplicate joins across historical pickup assignments.
    if org.org_type == 'COLLECTION_COMPANY':
        eligible_line = (select(PickupRequestItem.id)
            .join(PickupRequest, PickupRequest.id == PickupRequestItem.pickup_request_id)
            .join(Vehicle, Vehicle.id == PickupRequest.assigned_vehicle_id)
            .where(PickupRequestItem.waste_record_id == InvoiceLine.waste_record_id,
                   Vehicle.organization_id == org_id,
                   PickupRequest.collected_at.is_not(None))
            .exists())
        kind = 'collection'
    else:
        eligible_line = (select(ProcessingRecord.id)
            .join(TreatmentFacilityProfile,
                  TreatmentFacilityProfile.id == ProcessingRecord.facility_id)
            .where(ProcessingRecord.waste_record_id == InvoiceLine.waste_record_id,
                   TreatmentFacilityProfile.organization_id == org_id,
                   ProcessingRecord.completed_at.is_not(None))
            .exists())
        kind = 'treatment'
    stmt = (select(InvoiceLine, HospitalInvoice)
            .join(HospitalInvoice, HospitalInvoice.id == InvoiceLine.invoice_id)
            .where(eligible_line)
            .order_by(HospitalInvoice.issued_at.desc(), InvoiceLine.id))
    rows = list(db.execute(stmt).all())
    records = []
    accrued = Decimal('0.00')
    paid_invoice_accrual = Decimal('0.00')
    for line, invoice in rows:
        amount = money(line.collection_bdt if kind == 'collection' else line.treatment_bdt)
        accrued += amount
        # Full invoice settlement is NOT the same as an operator payout.
        if invoice.state == 'paid':
            paid_invoice_accrual += amount
        records.append({'invoice_id': str(invoice.id), 'waste_record_id': str(line.waste_record_id),
            'issued_at': invoice.issued_at.isoformat() if invoice.issued_at else None,
            'amount_bdt': amount, 'invoice_state': invoice.state,
            'source': f'{kind}_verified_batch'})
    recycling = Decimal('0.00')
    if org.org_type == 'TREATMENT_FACILITY':
        recycling = sum((Decimal(str(x)) for x in db.scalars(
            select(RecyclingAllocation.facility_share_bdt)
            .join(RecyclingSale, RecyclingSale.id == RecyclingAllocation.sale_id)
            .where(RecyclingSale.facility_org_id == org_id)).all()), Decimal('0.00'))
    return {
        'organization_id': str(org_id), 'role': org.org_type,
        'currency': 'BDT', 'settlement_status': 'not_tracked',
        'accrued_service_bdt': money(accrued),
        'accrued_on_paid_invoices_bdt': money(paid_invoice_accrual),
        'accrued_on_unpaid_invoices_bdt': money(accrued - paid_invoice_accrual),
        'recycling_profit_share_bdt': money(recycling),
        'total_accrued_bdt': money(accrued + recycling),
        'line_count': len(records), 'recent_lines': records[:50],
        'note': 'Accrued amounts are not evidence of cash transfer or settlement. No operator payout ledger is present.',
    }
