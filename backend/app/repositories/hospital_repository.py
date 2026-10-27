import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.services.organization_eligibility import eligible_member_organizations, profile_organization
from app.services.organization_context import selected_org_id

from app.models.hospital_profile import HospitalProfile
from app.schemas.hospital import HospitalProfileCreate, HospitalProfileUpdate


class HospitalRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_user_id(self, user_id: uuid.UUID) -> HospitalProfile | None:
        """Select only a profile reachable via active company membership.

        For a multi-company user, an explicit X-Organization-ID is required.
        Unlinked legacy profiles remain available only to their direct owner.
        """
        from app.models.business import OrganizationMember
        wanted = selected_org_id()
        statement = select(HospitalProfile).join(
            OrganizationMember,
            OrganizationMember.organization_id == HospitalProfile.organization_id,
        ).where(OrganizationMember.user_id == user_id,
                OrganizationMember.active.is_(True))
        if wanted is not None:
            statement = statement.where(HospitalProfile.organization_id == wanted)
        linked = list(self.db.scalars(statement.limit(2)).all())
        if wanted is not None:
            return linked[0] if len(linked) == 1 else None
        # Unambiguous linked membership takes priority over legacy records.
        if len(linked) > 1:
            return None
        if linked:
            return linked[0]
        return self.db.scalar(select(HospitalProfile).where(
            HospitalProfile.user_id == user_id,
            HospitalProfile.organization_id.is_(None)).limit(1))

    def get_by_id(self, hospital_id: uuid.UUID) -> HospitalProfile | None:
        return self.db.get(HospitalProfile, hospital_id)

    def create(self, *, user_id: uuid.UUID, data: HospitalProfileCreate) -> HospitalProfile:
        companies = eligible_member_organizations(self.db, user_id, "HOSPITAL")
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
            raise ValueError("Select a hospital organization before creating a profile")
        profile = HospitalProfile(user_id=user_id,
            organization_id=target,
            **data.model_dump())
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def update(
        self, *, profile: HospitalProfile, data: HospitalProfileUpdate
    ) -> HospitalProfile:
        for field, value in data.model_dump().items():
            setattr(profile, field, value)
        self.db.commit()
        self.db.refresh(profile)
        return profile
