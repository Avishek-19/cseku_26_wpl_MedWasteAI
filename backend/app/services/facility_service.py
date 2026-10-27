from decimal import Decimal
import uuid

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.services.organization_eligibility import can_manage_profile

from app.models.facility_profile import TreatmentFacilityProfile
from app.models.user import User
from app.repositories.facility_repository import FacilityRepository
from app.repositories.waste_category_repository import WasteCategoryRepository
from app.schemas.facility import (
    FacilityDashboardStats,
    FacilityProfileCreate,
    FacilityProfileUpdate,
)


class ProfileAlreadyExistsError(Exception):
    pass


class ProfileNotFoundError(Exception):
    pass


class ProfileAccessDeniedError(Exception):
    pass


class InvalidCategoryError(Exception):
    pass


class FacilityService:
    VALID_SERVICES = {
        "AUTOCLAVE", "INCINERATION", "CHEMICAL_TREATMENT", "MICROWAVE_TREATMENT",
        "SHARPS_DESTRUCTION", "PHARMACEUTICAL_TREATMENT", "RECYCLING",
        "MATERIAL_RECOVERY", "FINAL_DISPOSAL", "SPECIALIZED_TREATMENT",
    }

    @classmethod
    def _validate_services(cls, services: list[str]) -> list[str]:
        normalized = [s.strip().upper() for s in services if s and s.strip()]
        if any(s not in cls.VALID_SERVICES for s in normalized):
            raise ValueError("Unknown processing service.")
        return list(dict.fromkeys(normalized))

    @staticmethod
    def _validate_other_services(services: list[str]) -> list[str]:
        cleaned = [s.strip() for s in services if s and s.strip()]
        if any(len(s) > 120 for s in cleaned):
            raise ValueError("Other service names must be 120 characters or fewer.")
        return list(dict.fromkeys(cleaned))[:20]

    def __init__(self, db: Session):
        self.db = db
        self.repo = FacilityRepository(db)
        self.categories = WasteCategoryRepository(db)

    def get_profile(self, user_id: uuid.UUID) -> TreatmentFacilityProfile | None:
        return self.repo.get_by_user_id(user_id)

    def create_profile(
        self, *, user_id: uuid.UUID, data: FacilityProfileCreate
    ) -> TreatmentFacilityProfile:
        if self.repo.get_by_user_id(user_id):
            raise ProfileAlreadyExistsError()
        data.processing_services = self._validate_services(data.processing_services)
        data.other_services = self._validate_other_services(data.other_services)
        self._validate_category_ids(data.accepted_category_ids)
        profile_data = data.model_dump(exclude={"accepted_category_ids"})
        try:
            profile = self.repo.create(user_id=user_id, data=FacilityProfileCreate(**profile_data), commit=False)
        except IntegrityError:
            self.db.rollback()
            raise ProfileAlreadyExistsError()
        if data.accepted_category_ids:
            self.repo.set_accepted_categories(facility_id=profile.id, category_ids=data.accepted_category_ids, commit=False)
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def update_profile(
        self, *, user_id: uuid.UUID, data: FacilityProfileUpdate
    ) -> TreatmentFacilityProfile:
        profile = self.repo.get_by_user_id(user_id)
        if profile is None:
            raise ProfileNotFoundError()
        if not can_manage_profile(self.db, profile, user_id, "TREATMENT_FACILITY"):
            raise ProfileAccessDeniedError()
        data.processing_services = self._validate_services(data.processing_services)
        data.other_services = self._validate_other_services(data.other_services)
        self._validate_category_ids(data.accepted_category_ids)
        if data.capacity_kg < profile.current_utilization_kg:
            raise ValueError("Capacity cannot be reduced below the reserved or occupied load.")
        profile_data = data.model_dump(exclude={"accepted_category_ids"})
        updated = self.repo.update(profile=profile, data=FacilityProfileUpdate(**profile_data), commit=False)
        self.repo.set_accepted_categories(facility_id=profile.id, category_ids=data.accepted_category_ids, commit=False)
        self.db.commit()
        self.db.refresh(updated)
        return updated

    def _validate_category_ids(self, category_ids: list[uuid.UUID]):
        for category_id in category_ids:
            category = self.categories.get_by_id(category_id)
            if category is None or not category.is_active or category.code == "PENDING":
                raise InvalidCategoryError()

    def get_accepted_categories(self, user_id: uuid.UUID):
        profile = self.repo.get_by_user_id(user_id)
        if profile is None:
            raise ProfileNotFoundError()
        return self.repo.list_accepted_categories(profile.id)

    def set_accepted_categories(self, *, user_id: uuid.UUID, category_ids: list[uuid.UUID]):
        profile = self.repo.get_by_user_id(user_id)
        if profile is None:
            raise ProfileNotFoundError()
        if not can_manage_profile(self.db, profile, user_id, "TREATMENT_FACILITY"):
            raise ProfileAccessDeniedError()

        for category_id in category_ids:
            category = self.categories.get_by_id(category_id)
            if category is None or not category.is_active or category.code == "PENDING":
                raise InvalidCategoryError()

        self.repo.set_accepted_categories(facility_id=profile.id, category_ids=category_ids)
        return self.repo.list_accepted_categories(profile.id)

    def get_dashboard_stats(self, *, user: User) -> FacilityDashboardStats:
        profile = self.repo.get_by_user_id(user.id)
        accepted_count = (
            len(self.repo.list_accepted_categories(profile.id)) if profile else 0
        )
        utilization_percent = None
        if profile and profile.capacity_kg:
            utilization_percent = round(
                float(profile.current_utilization_kg) / float(profile.capacity_kg) * 100, 1
            )

        from app.services.organization_eligibility import eligible_facility
        return FacilityDashboardStats(
            profile_complete=profile is not None,
            is_verified=profile.is_verified if profile else False,
            member_since=user.created_at,
            facility_type=profile.facility_type if profile else "Waste Processing Facility",
            processing_services=profile.processing_services if profile else [],
            other_services=profile.other_services if profile else [],
            availability_status=profile.availability_status if profile else "unavailable",
            capacity_kg=profile.capacity_kg if profile else None,
            current_utilization_kg=profile.current_utilization_kg if profile else None,
            available_capacity_kg=Decimal(str(profile.available_capacity_kg)) if profile else None,
            utilization_percent=utilization_percent,
            accepted_category_count=accepted_count,
            matching_available=bool(profile and eligible_facility(self.db, profile, new_work=True)),
            incoming_waste_count=self.repo.incoming_count(profile.id) if profile else 0,
            processing_queue_count=self.repo.processing_queue_count(profile.id) if profile else 0,
        )
