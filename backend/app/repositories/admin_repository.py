import uuid
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.hospital_profile import HospitalProfile
from app.models.incident import Incident
from app.models.risk_rule import RiskRule
from app.models.roles import UserRole
from app.models.user import User
from app.models.waste_category import WasteCategory
from app.models.waste_record import WasteRecord


class AdminRepository:
    def __init__(self, db: Session): self.db = db

    def users(self, role: UserRole | None = None) -> list[User]:
        stmt = select(User).order_by(User.created_at.desc())
        if role: stmt = stmt.where(User.role == role)
        return list(self.db.execute(stmt).scalars().all())

    def profile_verifications(self, role: UserRole, pending_only: bool) -> tuple[list, int]:
        if role == UserRole.HOSPITAL:
            profile, org = HospitalProfile, HospitalProfile.name
        elif role == UserRole.FACILITY:
            profile, org = TreatmentFacilityProfile, TreatmentFacilityProfile.name
        else:
            users = select(User).where(User.role == UserRole.COLLECTOR).order_by(User.created_at.desc())
            if pending_only: users = users.where(User.is_verified.is_(False))
            rows = self.db.execute(users).scalars().all()
            return [(u.id, u.id, u.full_name, u.email, u.full_name, "—", "—", u.is_verified, u.created_at) for u in rows], len(rows)
        stmt = select(profile, User).join(User, User.id == profile.user_id).order_by(profile.created_at.desc())
        if pending_only: stmt = stmt.where(profile.is_verified.is_(False))
        rows = self.db.execute(stmt).all()
        return rows, len(rows)

    def category_list(self) -> list[WasteCategory]:
        return list(self.db.execute(select(WasteCategory).order_by(WasteCategory.name)).scalars().all())

    def incident_list(self, open_only: bool = False) -> list[tuple[Incident, WasteRecord]]:
        stmt = select(Incident, WasteRecord).join(WasteRecord, WasteRecord.id == Incident.waste_record_id).order_by(Incident.created_at.desc())
        if open_only: stmt = stmt.where(Incident.is_resolved.is_(False))
        return list(self.db.execute(stmt).all())

    def risk_rules(self) -> list[tuple[RiskRule, WasteCategory]]:
        stmt = select(RiskRule, WasteCategory).join(WasteCategory, WasteCategory.id == RiskRule.category_id).order_by(WasteCategory.name)
        return list(self.db.execute(stmt).all())

    def audit_logs(self, limit: int = 100) -> list[tuple[AuditLog, User | None]]:
        stmt = select(AuditLog, User).outerjoin(User, User.id == AuditLog.actor_user_id).order_by(AuditLog.created_at.desc()).limit(limit)
        return list(self.db.execute(stmt).all())

    def overview_counts(self) -> dict:
        def count(model, condition=None):
            stmt = select(func.count()).select_from(model)
            if condition is not None: stmt = stmt.where(condition)
            return int(self.db.execute(stmt).scalar_one())
        return {
            "users_total": count(User),
            "active_users": count(User, User.is_active.is_(True)),
            "pending_hospitals": count(HospitalProfile, HospitalProfile.is_verified.is_(False)),
            "pending_collectors": count(User, (User.role == UserRole.COLLECTOR) & User.is_verified.is_(False)),
            "pending_facilities": count(TreatmentFacilityProfile, TreatmentFacilityProfile.is_verified.is_(False)),
            "open_incidents": count(Incident, Incident.is_resolved.is_(False)),
            "waste_batches": count(WasteRecord),
            "audit_events": count(AuditLog),
        }

    def add_audit(self, actor_id, action, entity_type, entity_id=None, details=None):
        row = AuditLog(actor_user_id=actor_id, action=action, entity_type=entity_type, entity_id=str(entity_id) if entity_id else None, details=details or {})
        self.db.add(row)
        return row
