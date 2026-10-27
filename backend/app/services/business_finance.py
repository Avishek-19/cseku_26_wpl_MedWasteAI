"""Deterministic BDT accounting rules, explicit posted records, no wallet balances."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models.business import (
    Organization, OrganizationMember, OrganizationPermit, BillingContract, ContractRate,
    HospitalInvoice, InvoiceLine, InvoiceAdjustment, PaymentIntent, RecyclingSale, RecyclingSaleLot, RecyclingAllocation,
    OperatorJobEvent, Subscription, Journal, JournalLine,
)
from app.models.hospital_profile import HospitalProfile
from app.models.waste_record import WasteRecord
from app.models.waste_event import WasteEvent
from app.models.waste_enums import WasteEventType, WasteStatus, WasteUnit, PickupStatus
from app.models.processing_record import ProcessingRecord
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.collection_proof import CollectionProof
from app.models.vehicle import Vehicle
from app.models.audit_log import AuditLog

DHAKA = ZoneInfo('Asia/Dhaka')
CENT = Decimal('0.01')

def money(value) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Invalid financial amount')
    return result.quantize(CENT, rounding=ROUND_HALF_UP)


def bill_due(gross, credit, paid=0) -> Decimal:
    return max(Decimal('0.00'), money(gross) - money(credit) - money(paid))


def recycling_split(proceeds, approved_costs) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    if money(proceeds) < 0 or money(approved_costs) < 0:
        raise ValueError('Negative proceeds/costs require a documented reversal entry')
    net = max(Decimal('0.00'), money(proceeds) - money(approved_costs))
    hospital = money(net * Decimal('0.60'))
    facility = money(net * Decimal('0.30'))
    platform = net - hospital - facility  # residual cent preserves exact balance
    return net, hospital, facility, platform


def cycle_for(anchor_local: date, when_utc: datetime, cycle_days: int = 15):
    if when_utc.tzinfo is None:
        raise ValueError('UTC-aware timestamp required')
    if cycle_days < 1:
        raise ValueError('Invalid billing cycle')
    local_day = when_utc.astimezone(DHAKA).date()
    n = (local_day - anchor_local).days // cycle_days
    if n < 0:
        raise ValueError('Completion predates signed contract')
    start = anchor_local + timedelta(days=n * cycle_days)
    end = start + timedelta(days=cycle_days)
    start_utc = datetime.combine(start, datetime.min.time(), DHAKA).astimezone(timezone.utc)
    end_utc = datetime.combine(end, datetime.min.time(), DHAKA).astimezone(timezone.utc)
    return n, start_utc, end_utc


def journal(db: Session, *, unique_event: str, description: str,
            entries: list[tuple[str, str, Decimal, object | None]]) -> Journal:
    """Atomic append-only balanced journal. Caller owns transaction boundary."""
    existing = db.scalar(select(Journal).where(Journal.unique_event == unique_event))
    if existing:
        return existing
    debits = sum((money(e[2]) for e in entries if e[1] == 'debit'), Decimal('0.00'))
    credits = sum((money(e[2]) for e in entries if e[1] == 'credit'), Decimal('0.00'))
    if debits != credits or debits <= 0 or any(e[1] not in ('debit', 'credit') or money(e[2]) <= 0 for e in entries):
        raise ValueError('Journal entries must be positive and balanced')
    item = Journal(unique_event=unique_event, description=description)
    db.add(item)
    db.flush()
    for account, side, amount, organization_id in entries:
        db.add(JournalLine(journal_id=item.id, account=account, side=side,
                           amount_bdt=money(amount), organization_id=organization_id))
    db.flush()
    return item


def assert_member(db: Session, user, org_id, roles=None) -> Organization:
    org = db.get(Organization, org_id)
    if not org:
        raise PermissionError('Unknown organization')
    if user.role.value == 'admin':
        return org
    member = db.scalar(select(OrganizationMember).where(
        OrganizationMember.organization_id == org_id, OrganizationMember.user_id == user.id,
        OrganizationMember.active.is_(True)))
    if member is None or (roles and member.member_role not in roles):
        raise PermissionError('Organization membership required')
    return org


def permits_current(db: Session, org_id, at: date) -> bool:
    """For each permit type, at least one approved and unexpired version must exist.

    Expired/rejected predecessor versions do not veto an approved renewal.
    A pending renewal does not prematurely revoke a still-valid approval.
    """
    permits = list(db.scalars(select(OrganizationPermit).where(
        OrganizationPermit.organization_id == org_id)).all())
    if not permits:
        return False
    groups = {}
    for p in permits:
        groups.setdefault(p.permit_type.strip().casefold(), []).append(p)
    return all(any(p.approval_status == 'approved' and
                   (p.expires_on is None or p.expires_on > at)
                   for p in versions) for versions in groups.values())


def operator_accepts_new_work(db: Session, org_id, at: date) -> bool:
    org = db.get(Organization, org_id)
    if org is None or org.org_type not in {'COLLECTION_COMPANY', 'TREATMENT_FACILITY'} or org.status != 'verified':
        return False
    if not permits_current(db, org_id, at):
        return False
    completed = db.scalar(select(func.count()).select_from(OperatorJobEvent).where(
        OperatorJobEvent.organization_id == org_id, OperatorJobEvent.reversed_at.is_(None))) or 0
    if completed < 5:
        return True
    sub = db.scalar(select(Subscription.id).where(
        Subscription.organization_id == org_id, Subscription.state == 'paid',
        Subscription.period_start <= at, Subscription.period_end > at).limit(1))
    return sub is not None


def verified_service_payees(db: Session, record: WasteRecord) -> tuple[object, object]:
    """Resolve the *actual* collection and processing payees, never a guess.

    Each fee is credited to a verified service chain: a single collected
    pickup with a handover proof and its assigned company's vehicle, and a
    completed processing record with the facility's organization.  Missing
    legacy ownership blocks invoicing until reconciled; no unassigned payable
    is allowed into the ledger.
    """
    pickups = list(db.scalars(select(PickupRequest).join(
        PickupRequestItem, PickupRequestItem.pickup_request_id == PickupRequest.id
    ).join(CollectionProof, CollectionProof.pickup_id == PickupRequest.id).where(
        PickupRequestItem.waste_record_id == record.id,
        PickupRequest.hospital_id == record.hospital_id,
    )).all())
    if len(pickups) != 1:
        raise ValueError('exactly one pickup with completed collection proof is required')
    pickup = pickups[0]
    if pickup.status != PickupStatus.COMPLETED:
        raise ValueError('collection pickup must be completed before settlement')
    if pickup.assigned_vehicle_id is None:
        raise ValueError('collected pickup has no attributable vehicle')
    vehicle = db.get(Vehicle, pickup.assigned_vehicle_id)
    company = db.get(Organization, vehicle.organization_id) if vehicle and vehicle.organization_id else None
    if company is None or company.org_type != 'COLLECTION_COMPANY':
        raise ValueError('collection company organization is missing or invalid')

    processing = db.scalar(select(ProcessingRecord).where(
        ProcessingRecord.waste_record_id == record.id,
        ProcessingRecord.completed_at.is_not(None),
    ).limit(1))
    facility = db.get(TreatmentFacilityProfile, processing.facility_id) if processing else None
    facility_org = db.get(Organization, facility.organization_id) if facility and facility.organization_id else None
    if facility_org is None or facility_org.org_type != 'TREATMENT_FACILITY':
        raise ValueError('treatment facility organization is missing or invalid')
    return company.id, facility_org.id


def service_payable_entries(line_data: list, payees: dict) -> list[tuple]:
    """Group payable credits by account AND receiving organization."""
    grouped: dict[tuple[str, object | None], Decimal] = {}
    for record, _, collection, treatment, platform in line_data:
        collection_org, facility_org = payees[record.id]
        for account, amount, org_id in (
            ('operator_collection_payable', collection, collection_org),
            ('facility_treatment_payable', treatment, facility_org),
            ('platform_service_revenue', platform, None),
        ):
            if amount > 0:
                key = (account, org_id)
                grouped[key] = money(grouped.get(key, Decimal('0')) + amount)
    return [(account, 'credit', amount, org_id) for (account, org_id), amount in
            sorted(grouped.items(), key=lambda item: (item[0][0], str(item[0][1])))]


def issue_invoice(db: Session, contract: BillingContract, cycle_number: int, *, actor_user_id=None) -> HospitalInvoice:
    """Issue immutable snapshot for exactly one local 15-day cycle.

    Only VERIFIED COMPLETED medical-waste batches with measured kg and an
    effective contract rate are eligible. Known incomplete batches block issue.
    Late batches amend only unpaid, non-checkout invoices via append-only audit
    and balanced journal entries; paid invoices require reviewed credit notes.
    """
    if cycle_number < 0 or not contract.active:
        raise ValueError('Invalid billing period or inactive contract')
    # Serialize issuance for this contract, including when the invoice does
    # not exist yet (locking a missing invoice row cannot prevent a race).
    db.scalar(select(BillingContract).where(BillingContract.id == contract.id).with_for_update(of=BillingContract))
    found = db.scalar(select(HospitalInvoice).where(
        HospitalInvoice.contract_id == contract.id,
        HospitalInvoice.cycle_number == cycle_number).with_for_update(of=HospitalInvoice))
    start_local = contract.billing_anchor_local + timedelta(days=cycle_number * contract.cycle_days)
    n, start, end = cycle_for(contract.billing_anchor_local,
        datetime.combine(start_local, datetime.min.time(), DHAKA).astimezone(timezone.utc),
        contract.cycle_days)
    assert n == cycle_number
    if end > datetime.now(timezone.utc):
        raise ValueError('Cannot issue a final immutable invoice for an unclosed or future billing cycle')
    hospital_org = db.get(Organization, contract.hospital_org_id)
    if not hospital_org or hospital_org.org_type != 'HOSPITAL':
        raise ValueError('Contract must belong to hospital organization')
    profile = db.scalar(select(HospitalProfile).where(
        HospitalProfile.organization_id == hospital_org.id).limit(1)) or db.scalar(
        select(HospitalProfile).where(HospitalProfile.user_id == hospital_org.owner_user_id,
            HospitalProfile.organization_id.is_(None)).limit(1))
    if not profile:
        raise ValueError('Hospital profile missing')
    completed_in_cycle = select(WasteEvent.waste_record_id).where(
        WasteEvent.event_type == WasteEventType.COMPLETED,
        WasteEvent.created_at >= start,
        WasteEvent.created_at < end)
    rows = list(db.scalars(select(WasteRecord).where(
        WasteRecord.hospital_id == profile.id,
        WasteRecord.status == WasteStatus.COMPLETED,
        WasteRecord.id.in_(completed_in_cycle)).with_for_update(of=WasteRecord)).all())
    # Every completed batch belongs to this cycle even if a rate or measured
    # weight is missing. Never silently finalize a partial 15-day snapshot.
    line_data = []
    payees = {}
    held = []
    already_invoiced_elsewhere = []
    for record in rows:
        prior_line = db.scalar(select(InvoiceLine).where(
            InvoiceLine.waste_record_id == record.id).limit(1))
        if prior_line is not None:
            if found is None or prior_line.invoice_id != found.id:
                already_invoiced_elsewhere.append(record.waste_code)
            continue
        if record.unit != WasteUnit.KG or record.received_quantity is None or record.received_at is None:
            held.append((record.waste_code, 'missing verified kg/receipt'))
            continue
        proof = db.scalar(select(ProcessingRecord.id).where(
            ProcessingRecord.waste_record_id == record.id, ProcessingRecord.completed_at.is_not(None)).limit(1))
        if not proof:
            held.append((record.waste_code, 'missing completed processing proof'))
            continue
        received_at = record.received_at
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        rate = db.scalar(select(ContractRate).where(
            ContractRate.contract_id == contract.id, ContractRate.category_id == record.category_id,
            ContractRate.effective_from <= received_at.astimezone(DHAKA).date())
            .order_by(ContractRate.effective_from.desc()).limit(1))
        if not rate:
            held.append((record.waste_code, 'missing effective category rate'))
            continue
        kg = Decimal(str(record.received_quantity))
        if not kg.is_finite() or kg <= 0:
            held.append((record.waste_code, 'invalid received weight'))
            continue
        cc = money(kg * rate.collection_rate)
        tc = money(kg * rate.treatment_rate)
        pc = money(kg * rate.platform_rate)
        try:
            # Even legacy batches need a real recipient before recognizing
            # collection/treatment liabilities. Never post anonymous payables.
            payees[record.id] = verified_service_payees(db, record)
        except ValueError as exc:
            held.append((record.waste_code, str(exc)))
            continue
        line_data.append((record, kg, cc, tc, pc))
    if already_invoiced_elsewhere:
        raise ValueError('Completed waste already invoiced under a different cycle: ' +
                         ', '.join(already_invoiced_elsewhere[:5]))
    if held:
        raise ValueError('Invoice cannot be finalized; completed waste batches require reconciliation: ' +
                         '; '.join(f'{code}: {reason}' for code, reason in held[:8]))
    if found is not None:
        if not line_data:
            return found
        # An already paid/part-paid or pending-checkout invoice may be
        # under settlement. Never silently change its amount under a payer.
        if found.state != 'issued' or money(found.paid_bdt) != 0:
            raise ValueError('Paid or partially paid invoice requires a reviewed credit/debit note; no automatic adjustment allowed.')
        payment_started = db.scalar(select(PaymentIntent.id).where(
            PaymentIntent.target_kind == 'invoice', PaymentIntent.target_id == found.id,
            PaymentIntent.state.notin_(['failed', 'cancelled', 'expired', 'rejected'])
        ).limit(1))
        if payment_started is not None:
            raise ValueError('Invoice has an existing checkout/payment intent; reconcile payment before adjusting it.')
        previous = money(found.gross_bdt)
        # Append-only adjustment records + balanced additional journal entries
        # document every correction without modifying historical postings.
        for record, kg, cc, tc, pc in line_data:
            amount = money(cc + tc + pc)
            adjustment = InvoiceAdjustment(invoice_id=found.id, waste_record_id=record.id,
                measured_kg=kg, collection_bdt=cc, treatment_bdt=tc,
                platform_bdt=pc, total_bdt=amount,
                reason='Verified late batch added to closed billing cycle',
                actor_user_id=actor_user_id)
            db.add(adjustment)
            db.add(InvoiceLine(invoice_id=found.id, waste_record_id=record.id,
                measured_kg=kg, collection_bdt=cc, treatment_bdt=tc,
                platform_bdt=pc, total_bdt=amount))
            db.flush()
            if amount > 0:
                journal(db, unique_event=f'invoice_adjustment:{adjustment.id}',
                    description='Late verified service adjustment',
                    entries=[('hospital_receivable','debit',amount,hospital_org.id)] +
                    service_payable_entries([(record, kg, cc, tc, pc)], payees))
        found.gross_bdt = money(previous + sum((cc + tc + pc for _,_,cc,tc,pc in line_data), Decimal('0')))
        found.due_bdt = bill_due(found.gross_bdt, found.credits_bdt)
        db.add(AuditLog(actor_user_id=actor_user_id, action='billing.invoice_adjusted',
            entity_type='hospital_invoice', entity_id=str(found.id),
            details={'prior_gross_bdt':str(previous),'new_gross_bdt':str(found.gross_bdt),
                     'added_batches':[rec.waste_code for rec,*_ in line_data],
                     'reason':'Automatic recovery of newly verified late batches'}))
        db.commit()
        db.refresh(found)
        return found
    gross = sum((cc + tc + pc for _, _, cc, tc, pc in line_data), Decimal('0.00'))
    credits = list(db.scalars(select(RecyclingAllocation).where(
        RecyclingAllocation.hospital_org_id == hospital_org.id,
        RecyclingAllocation.credit_remaining_bdt > 0).order_by(RecyclingAllocation.id).with_for_update(of=RecyclingAllocation)).all())
    applied = Decimal('0.00')
    for credit in credits:
        part = min(Decimal(str(credit.credit_remaining_bdt)), gross - applied)
        if part <= 0: break
        credit.credit_remaining_bdt = money(Decimal(str(credit.credit_remaining_bdt)) - part)
        applied += part
    invoice = HospitalInvoice(contract_id=contract.id, hospital_org_id=hospital_org.id,
        cycle_number=cycle_number, cycle_start=start, cycle_end=end,
        gross_bdt=money(gross), credits_bdt=money(applied), due_bdt=bill_due(gross, applied), paid_bdt=money(0))
    db.add(invoice)
    db.flush()
    for record, kg, cc, tc, pc in line_data:
        db.add(InvoiceLine(invoice_id=invoice.id, waste_record_id=record.id,
            measured_kg=kg, collection_bdt=cc, treatment_bdt=tc, platform_bdt=pc,
            total_bdt=cc+tc+pc))
    if gross > 0:
        journal(db, unique_event=f'invoice:{invoice.id}', description='Verified service invoice',
            entries=[('hospital_receivable','debit',gross,hospital_org.id)] +
            service_payable_entries(line_data, payees))
    if applied > 0:
        journal(db, unique_event=f'credit_apply:{invoice.id}', description='Apply realized hospital recycling credit',
            entries=[('hospital_recycling_credit_liability','debit',applied,hospital_org.id),
                     ('hospital_receivable','credit',applied,hospital_org.id)])
    db.commit()
    db.refresh(invoice)
    return invoice


def verified_recycling_lot_basis(db: Session, sale: RecyclingSale, *, lot_ids: list | None = None) -> dict:
    """Recompute hospital weights from immutable, completed, facility-bound batches.

    Measured received kg is used as a documented proportional proxy for input
    contribution; recovered resale yield is NOT present in the current schema.
    No client-provided hospital weight is accepted.
    """
    profile = db.scalar(select(TreatmentFacilityProfile).where(
        TreatmentFacilityProfile.organization_id == sale.facility_org_id).limit(1))
    if profile is None or not profile.is_verified:
        raise ValueError('Verified treatment facility profile is required')
    if lot_ids is not None:
        if len(lot_ids) != len(set(lot_ids)) or not lot_ids:
            raise ValueError('Recycling sale requires unique verified waste batch IDs')
        records = [db.scalar(select(WasteRecord).where(WasteRecord.id == ident).with_for_update(of=WasteRecord)) for ident in lot_ids]
        if any(rec is None for rec in records):
            raise ValueError('Waste batch not found')
    else:
        lots = list(db.scalars(select(RecyclingSaleLot).where(
            RecyclingSaleLot.sale_id == sale.id).order_by(RecyclingSaleLot.waste_record_id).with_for_update(of=RecyclingSaleLot)).all())
        if not lots:
            raise ValueError('Verified recycling lots required before allocation')
        records = [db.scalar(select(WasteRecord).where(
            WasteRecord.id == lot.waste_record_id).with_for_update(of=WasteRecord)) for lot in lots]
    weights: dict = {}
    for i, record in enumerate(records):
        if record is None or record.status != WasteStatus.COMPLETED or record.unit != WasteUnit.KG:
            raise ValueError('Only completed kilogram waste batches can back recycling allocations')
        if record.category is None or not record.category.is_recyclable:
            raise ValueError('Only waste categories verified as recyclable can back recycling sales')
        processing = db.scalar(select(ProcessingRecord).where(
            ProcessingRecord.waste_record_id == record.id).with_for_update(of=ProcessingRecord))
        if (processing is None or processing.completed_at is None
            or processing.facility_id != profile.id
            or processing.processing_method.upper() not in {'RECYCLING', 'MATERIAL_RECOVERY'}):
            raise ValueError('Recycling proof must be completed by the sale facility')
        hospital = db.get(HospitalProfile, record.hospital_id)
        if hospital is None or hospital.organization_id is None:
            raise ValueError('Batch hospital must have an attributable organization')
        kg = Decimal(str(record.received_quantity)) if record.received_quantity is not None else Decimal('0')
        if not kg.is_finite() or kg <= 0:
            raise ValueError('Positive facility-measured received kilograms required')
        if lot_ids is None:
            lot = lots[i]
            if lot.hospital_org_id != hospital.organization_id or lot.contribution_kg != kg:
                raise ValueError('Verified recycling lot no longer matches its source batch')
        weights[hospital.organization_id] = weights.get(hospital.organization_id, Decimal('0')) + kg
    return weights


def record_recycling_distribution(db: Session, sale: RecyclingSale) -> list[RecyclingAllocation]:
    """Allocate the sale entirely from verified linked waste batches."""
    db.scalar(select(RecyclingSale).where(RecyclingSale.id == sale.id).with_for_update(of=RecyclingSale))
    if not sale.sale_payment_verified or sale.approved_by is None:
        raise PermissionError('Verified bank receipt and authorized approval required')
    if db.scalar(select(RecyclingAllocation.id).where(RecyclingAllocation.sale_id == sale.id)):
        raise ValueError('Already allocated; corrections require reversal entries')
    weights = verified_recycling_lot_basis(db, sale)
    net, hospital, facility, platform = recycling_split(sale.proceeds_bdt, sale.approved_costs_bdt)
    total = sum(weights.values())
    result = []
    remaining_h, remaining_f, remaining_p = hospital, facility, platform
    for i, (org_id, weight) in enumerate(sorted(weights.items(), key=lambda x: str(x[0]))):
        h = remaining_h if i == len(weights)-1 else money(hospital * weight / total)
        f = remaining_f if i == len(weights)-1 else money(facility * weight / total)
        pl = remaining_p if i == len(weights)-1 else money(platform * weight / total)
        remaining_h -= h;remaining_f -= f;remaining_p -= pl
        allocation = RecyclingAllocation(sale_id=sale.id, hospital_org_id=org_id,
            contribution_kg=weight, hospital_credit_bdt=h, credit_remaining_bdt=h,
            facility_share_bdt=f, platform_share_bdt=pl)
        db.add(allocation)
        result.append(allocation)
    proceeds = money(sale.proceeds_bdt)
    costs = money(sale.approved_costs_bdt)
    if proceeds > 0:
        journal(db, unique_event=f'recycle_gross:{sale.id}', description='Attested cleared recycling sale payment', entries=[
            ('bank_recycling_proceeds','debit',proceeds,None),
            ('recycling_gross_revenue','credit',proceeds,None),
        ])
    if costs > 0:
        journal(db, unique_event=f'recycle_costs:{sale.id}', description='Approved direct recycling costs (payable, not presumed paid)', entries=[
            ('recycling_direct_costs','debit',costs,None),
            ('recycling_costs_payable','credit',costs,None),
        ])
    if net > 0:
        journal(db, unique_event=f'recycle_distribution:{sale.id}', description='Allocate realized recycling net profit exactly once', entries=[
            ('recycling_profit_allocations','debit',net,None),
            # Liability belongs to the verified hospital organizations.  Do
            # not collapse it into an anonymous payable: invoice credit usage
            # must reconcile to the same hospital's credited journal lines.
            *((('hospital_recycling_credit_liability', 'credit', alloc.hospital_credit_bdt,
                 alloc.hospital_org_id) for alloc in result if alloc.hospital_credit_bdt > 0)),
            *(([('facility_recycling_payable','credit',facility,sale.facility_org_id)] if facility > 0 else [])),
            *(([('platform_recycling_revenue','credit',platform,None)] if platform > 0 else [])),
        ])
    db.commit()
    return result
