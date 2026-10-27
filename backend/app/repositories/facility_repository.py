import uuid

from sqlalchemy import delete, select, func
from sqlalchemy.orm import Session
from app.services.organization_eligibility import eligible_member_organizations, profile_organization
from app.services.organization_context import selected_org_id

from app.models.facility_accepted_category import FacilityAcceptedCategory
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.waste_category import WasteCategory
from app.models.user import User
from app.schemas.facility import FacilityProfileCreate, FacilityProfileUpdate


class FacilityRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_user_id(self, user_id: uuid.UUID) -> TreatmentFacilityProfile | None:
        """Select only a profile reachable via active company membership.

        For a multi-company user, an explicit X-Organization-ID is required.
        Unlinked legacy profiles remain available only to their direct owner.
        """
        from app.models.business import OrganizationMember
        wanted = selected_org_id()
        statement = select(TreatmentFacilityProfile).join(
            OrganizationMember,
            OrganizationMember.organization_id == TreatmentFacilityProfile.organization_id,
        ).where(OrganizationMember.user_id == user_id,
                OrganizationMember.active.is_(True))
        if wanted is not None:
            statement = statement.where(TreatmentFacilityProfile.organization_id == wanted)
        linked = list(self.db.scalars(statement.limit(2)).all())
        if wanted is not None:
            return linked[0] if len(linked) == 1 else None
        # Unambiguous linked membership takes priority over legacy records.
        if len(linked) > 1:
            return None
        if linked:
            return linked[0]
        return self.db.scalar(select(TreatmentFacilityProfile).where(
            TreatmentFacilityProfile.user_id == user_id,
            TreatmentFacilityProfile.organization_id.is_(None)).limit(1))

    @staticmethod
    def _profile_payload(data: FacilityProfileCreate | FacilityProfileUpdate) -> dict:
        """Return only fields that belong to the facility_profiles table.

        accepted_category_ids is an association-table payload, not a column on
        TreatmentFacilityProfile. Keep this guard in the repository so a
        defaulted Pydantic field can never leak into the SQLAlchemy constructor.
        """
        payload = data.model_dump()
        payload.pop("accepted_category_ids", None)
        return payload

    def create(
        self, *, user_id: uuid.UUID, data: FacilityProfileCreate, commit: bool = True
    ) -> TreatmentFacilityProfile:
        companies = eligible_member_organizations(self.db, user_id, "TREATMENT_FACILITY")
        from app.models.business import OrganizationMember
        target = (selected_org_id() if selected_org_id() in {c.id for c in companies}
                  else companies[0].id if len(companies) == 1 else None)
        if target is not None:
            role = self.db.scalar(select(OrganizationMember.member_role).where(
                OrganizationMember.organization_id == target,
                OrganizationMember.user_id == user_id,
                OrganizationMember.active.is_(True)).limit(1))
            if role not in {'owner', 'manager'}:
                raise PermissionError('Only company owner/manager may create its profile')

        if len(companies) > 1 and selected_org_id() not in {c.id for c in companies}:
            raise ValueError("Select a treatment facility organization before creating a profile")
        profile = TreatmentFacilityProfile(
            user_id=user_id,
            organization_id=target,
            **self._profile_payload(data),
        )
        self.db.add(profile)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(profile)
        return profile

    def update(
        self, *, profile: TreatmentFacilityProfile, data: FacilityProfileUpdate, commit: bool = True
    ) -> TreatmentFacilityProfile:
        for field, value in self._profile_payload(data).items():
            setattr(profile, field, value)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(profile)
        return profile

    def list_accepted_categories(self, facility_id: uuid.UUID) -> list[WasteCategory]:
        stmt = (
            select(WasteCategory)
            .join(FacilityAcceptedCategory, FacilityAcceptedCategory.category_id == WasteCategory.id)
            .where(FacilityAcceptedCategory.facility_id == facility_id)
            .order_by(WasteCategory.name)
        )
        return list(self.db.execute(stmt).scalars().all())

    def set_accepted_categories(
        self, *, facility_id: uuid.UUID, category_ids: list[uuid.UUID], commit: bool = True
    ) -> None:
        self.db.execute(
            delete(FacilityAcceptedCategory).where(
                FacilityAcceptedCategory.facility_id == facility_id
            )
        )
        for category_id in dict.fromkeys(category_ids):
            self.db.add(
                FacilityAcceptedCategory(facility_id=facility_id, category_id=category_id)
            )
        self.db.flush()
        if commit:
            self.db.commit()

    def list_accepting_category(self, category_id: uuid.UUID) -> list[TreatmentFacilityProfile]:
        stmt = (
            select(TreatmentFacilityProfile)
            .join(
                FacilityAcceptedCategory,
                FacilityAcceptedCategory.facility_id == TreatmentFacilityProfile.id,
            )
            .join(User, User.id == TreatmentFacilityProfile.user_id)
            .where(
                FacilityAcceptedCategory.category_id == category_id,
                User.is_active.is_(True),
            )
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_by_id(self, facility_id: uuid.UUID) -> TreatmentFacilityProfile | None:
        return self.db.get(TreatmentFacilityProfile, facility_id)

    def list_available_processing_facilities(self) -> list[TreatmentFacilityProfile]:
        stmt = select(TreatmentFacilityProfile).where(
            TreatmentFacilityProfile.is_verified.is_(True),
            TreatmentFacilityProfile.availability_status != "unavailable",
        )
        return list(self.db.execute(stmt).scalars().all())

    def incoming_count(self, facility_id: uuid.UUID) -> int:
        from app.models.matching_record import MatchingRecord
        from app.models.waste_record import WasteRecord
        stmt = select(func.count()).select_from(WasteRecord).join(
            MatchingRecord, MatchingRecord.waste_record_id == WasteRecord.id
        ).where(
            MatchingRecord.confirmed_facility_id == facility_id,
            WasteRecord.status == "in_transit",
        )
        return int(self.db.execute(stmt).scalar_one())

    def processing_queue_count(self, facility_id: uuid.UUID) -> int:
        from app.models.processing_record import ProcessingRecord
        stmt = select(func.count()).select_from(ProcessingRecord).where(
            ProcessingRecord.facility_id == facility_id,
            ProcessingRecord.status.in_(["received", "processing", "proof_submitted"]),
        )
        return int(self.db.execute(stmt).scalar_one())
