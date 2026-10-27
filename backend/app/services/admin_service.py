import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.hospital_profile import HospitalProfile
from app.models.incident import Incident
from app.models.risk_rule import RiskRule
from app.models.roles import UserRole
from app.models.user import User
from app.models.waste_category import WasteCategory
from app.repositories.admin_repository import AdminRepository


class AdminService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AdminRepository(db)

    def overview(self): return self.repo.overview_counts()
    def users(self, role=None): return self.repo.users(role)

    def update_user(self, actor: User, user_id: uuid.UUID, is_active: bool, is_verified: bool | None):
        user = self.db.get(User, user_id)
        if not user: return None
        if user.id == actor.id and not is_active: raise ValueError("You cannot disable your own admin account.")
        user.is_active = is_active
        if user.role == UserRole.COLLECTOR and is_verified is not None: user.is_verified = is_verified
        self.repo.add_audit(actor.id, "USER_UPDATED", "user", user.id, {"is_active": is_active, "is_verified": user.is_verified})
        self.db.commit(); self.db.refresh(user); return user

    def verification_list(self, role, pending_only):
        rows, total = self.repo.profile_verifications(role, pending_only)
        items=[]
        if role == UserRole.COLLECTOR:
            for row in rows:
                user_id, _, name, email, org, reg, city, verified, created = row
                items.append({"id": user_id, "user_id": user_id, "user_name": name, "email": email, "organization_name": org, "registration_number": reg, "city": city, "is_verified": verified, "created_at": created})
        else:
            for profile, user in rows:
                items.append({"id": profile.id, "user_id": user.id, "user_name": user.full_name, "email": user.email, "organization_name": profile.name, "registration_number": profile.registration_number, "city": profile.city, "is_verified": profile.is_verified, "created_at": profile.created_at})
        return items, total

    def set_verification(self, actor: User, role, profile_id, verified: bool):
        if role == UserRole.COLLECTOR:
            obj = self.db.get(User, profile_id)
            if not obj or obj.role != UserRole.COLLECTOR: return None
            obj.is_verified = verified
            entity_type = "user"
        else:
            model = {UserRole.HOSPITAL: HospitalProfile, UserRole.FACILITY: TreatmentFacilityProfile}[role]
            obj = self.db.get(model, profile_id)
            if not obj: return None
            obj.is_verified = verified
            entity_type = model.__tablename__
        self.repo.add_audit(actor.id, "VERIFICATION_CHANGED", entity_type, profile_id, {"role": role.value, "is_verified": verified})
        self.db.commit(); self.db.refresh(obj); return obj

    def create_category(self, actor, data):
        from sqlalchemy import func
        from sqlalchemy.exc import IntegrityError
        code = data.code.strip().upper()
        if code == 'PENDING':
            raise ValueError('PENDING is reserved for unclassified reports.')
        if self.db.scalar(select(WasteCategory.id).where(func.upper(WasteCategory.code) == code)):
            raise ValueError('Category code already exists.')
        if self.db.scalar(select(WasteCategory.id).where(WasteCategory.name == data.name)):
            raise ValueError('Category name already exists.')
        obj = WasteCategory(code=code, **data.model_dump(exclude={'code'}))
        self.db.add(obj)
        try:
            self.db.flush()
            self.repo.add_audit(actor.id, 'CATEGORY_CREATED', 'waste_category', obj.id,
                                {'code': obj.code, 'name': obj.name})
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ValueError('Category code or name already exists.')
        self.db.refresh(obj)
        return obj

    def update_category(self, actor, category_id, data):
        from sqlalchemy.exc import IntegrityError
        obj = self.db.get(WasteCategory, category_id)
        if not obj:
            return None
        changes = data.model_dump(exclude_unset=True)
        if obj.code == 'PENDING' and (changes.get('is_active') is False or changes.get('is_recyclable') is True):
            raise ValueError('The pending-report reference category cannot be disabled or made recyclable.')
        if any(value is None and key != 'description' for key, value in changes.items()):
            raise ValueError('Only the description may be cleared.')
        for key, value in changes.items():
            setattr(obj, key, value)
        self.repo.add_audit(actor.id, 'CATEGORY_UPDATED', 'waste_category', obj.id, changes)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ValueError('Category name already exists.')
        self.db.refresh(obj)
        return obj

    def risk_rules(self): return self.repo.risk_rules()
    def update_risk_rule(self, actor, category_id, data):
        category = self.db.get(WasteCategory, category_id)
        if not category:
            raise ValueError("Category not found.")
        obj=self.db.execute(select(RiskRule).where(RiskRule.category_id == category_id)).scalar_one_or_none()
        if not obj: obj=RiskRule(category_id=category_id); self.db.add(obj)
        for k,v in data.model_dump().items(): setattr(obj,k,v)
        self.repo.add_audit(actor.id,"RISK_RULE_UPDATED","risk_rule",obj.id,{"category_id":str(category_id),**data.model_dump(mode="json")}); self.db.commit(); self.db.refresh(obj); return obj

    def incidents(self, open_only=False):
        return self.repo.incident_list(open_only)
    def resolve_incident(self, actor, incident_id, resolved):
        obj=self.db.get(Incident, incident_id)
        if not obj: return None
        obj.is_resolved=resolved; self.repo.add_audit(actor.id,"INCIDENT_RESOLUTION_CHANGED","incident",obj.id,{"is_resolved":resolved}); self.db.commit(); self.db.refresh(obj); return obj
    def audit_logs(self, limit=100): return self.repo.audit_logs(limit)
