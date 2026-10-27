"""Locks and lifecycle gates shared by classification, risk and matching."""
from fastapi import HTTPException
from sqlalchemy import select
from app.models.waste_record import WasteRecord
from app.models.waste_enums import WasteStatus
from app.models.matching_record import MatchingRecord


def lock_reviewable(db, record, *, risk=False, matching=False):
    locked = db.scalar(select(WasteRecord).where(WasteRecord.id == record.id)
                       .with_for_update(of=WasteRecord).execution_options(populate_existing=True))
    if locked is None:
        raise HTTPException(404, "Waste record not found")
    allowed = {WasteStatus.CLASSIFIED, WasteStatus.RISK_ASSESSED} if risk else {
        WasteStatus.REPORTED, WasteStatus.CLASSIFIED, WasteStatus.RISK_ASSESSED}
    if matching:
        allowed = {WasteStatus.RISK_ASSESSED}
    if locked.status not in allowed:
        raise HTTPException(409, "This batch has progressed beyond review; classification, risk and destination cannot be changed")
    if not matching and db.scalar(select(MatchingRecord.id).where(
        MatchingRecord.waste_record_id == record.id, MatchingRecord.is_confirmed.is_(True)).limit(1)):
        raise HTTPException(409, "A confirmed destination locks classification and risk")
    return locked
