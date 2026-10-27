import uuid

from sqlalchemy.orm import Session
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.models.waste_record import WasteRecord
from app.services.organization_eligibility import can_manage_profile

from app.models.hospital_profile import HospitalProfile
from app.models.user import User
from app.repositories.hospital_repository import HospitalRepository
from app.schemas.hospital import (
    HospitalDashboardStats,
    HospitalProfileCreate,
    HospitalProfileUpdate,
)


class ProfileAlreadyExistsError(Exception):
    pass


class ProfileNotFoundError(Exception):
    pass


class ProfileAccessDeniedError(Exception):
    pass


class HospitalService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = HospitalRepository(db)

    def get_profile(self, user_id: uuid.UUID) -> HospitalProfile | None:
        return self.repo.get_by_user_id(user_id)

    def create_profile(
        self, *, user_id: uuid.UUID, data: HospitalProfileCreate
    ) -> HospitalProfile:
        if self.repo.get_by_user_id(user_id):
            raise ProfileAlreadyExistsError()
        try:
            return self.repo.create(user_id=user_id, data=data)
        except IntegrityError:
            self.db.rollback()
            raise ProfileAlreadyExistsError()

    def update_profile(
        self, *, user_id: uuid.UUID, data: HospitalProfileUpdate
    ) -> HospitalProfile:
        profile = self.repo.get_by_user_id(user_id)
        if profile is None:
            raise ProfileNotFoundError()
        if not can_manage_profile(self.db, profile, user_id, "HOSPITAL"):
            raise ProfileAccessDeniedError()
        return self.repo.update(profile=profile, data=data)

    def get_dashboard_stats(self, *, user: User) -> HospitalDashboardStats:
        profile = self.repo.get_by_user_id(user.id)
        return HospitalDashboardStats(
            profile_complete=profile is not None,
            is_verified=profile.is_verified if profile else False,
            member_since=user.created_at,
            total_waste_records=self.db.scalar(select(func.count()).select_from(WasteRecord).where(WasteRecord.hospital_id == profile.id)) if profile else 0,
            waste_tracking_available=profile is not None,
        )
