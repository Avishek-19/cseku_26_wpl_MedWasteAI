"""Single source of truth for company/profile eligibility and legacy ownership.

Legacy profiles remain readable; new writes should attach organization_id.
A verified profile alone does not authorize commercial work.
"""
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.business import Organization, OrganizationMember, OrganizationPermit
from app.models.user import User
from app.services.organization_context import selected_org_id


def profile_organization(db: Session, profile, org_type: str, *, verified: bool = True):
    org_id = getattr(profile, "organization_id", None)
    if org_id is not None:
        org = db.get(Organization, org_id)
        options = [org] if org else []
    else:
        # Only for legacy records. Never guess if the owner manages multiple companies.
        options = list(db.scalars(select(Organization).where(
            Organization.owner_user_id == profile.user_id,
            Organization.org_type == org_type)).all())
    options = [o for o in options if o.org_type == org_type]
    if len(options) != 1:
        return None
    org = options[0]
    if verified and org.status != 'verified':
        return None
    if verified:
        from app.services.business_finance import permits_current
        if not permits_current(db, org.id, date.today()):
            return None
    return org


def eligible_facility(db: Session, profile, *, need_capability=None, new_work=False):
    if not profile or not profile.is_verified or profile.availability_status == 'unavailable':
        return False
    org = profile_organization(db, profile, 'TREATMENT_FACILITY')
    if not org:
        return False
    if new_work:
        from app.services.business_finance import operator_accepts_new_work
        if not operator_accepts_new_work(db, org.id, date.today()):
            return False
    if need_capability:
        return str(need_capability).upper() in {str(v).upper() for v in (profile.processing_services or [])}
    return True


def eligible_member_organizations(db: Session, user_id, org_type):
    return list(db.scalars(select(Organization).join(OrganizationMember,
        OrganizationMember.organization_id == Organization.id).where(
        Organization.org_type == org_type,
        OrganizationMember.user_id == user_id,
        OrganizationMember.active.is_(True))).all())


def can_access_profile(db: Session, profile, user_id, org_type):
    if profile.user_id == user_id and getattr(profile, 'organization_id', None) is None:
        # Legacy profile owners may read unlinked data, never override linked membership.
        return True
    org = profile_organization(db, profile, org_type, verified=False)
    if org is None or (selected_org_id() is not None and selected_org_id() != org.id):
        return False
    return db.scalar(select(OrganizationMember.id).where(
        OrganizationMember.organization_id == org.id,
        OrganizationMember.user_id == user_id,
        OrganizationMember.active.is_(True)).limit(1)) is not None


def can_manage_profile(db: Session, profile, user_id, org_type):
    if profile.user_id == user_id and getattr(profile, 'organization_id', None) is None:
        # Legacy profile owners may read unlinked data, never override linked membership.
        return True
    org = profile_organization(db, profile, org_type, verified=False)
    if not org or (selected_org_id() is not None and selected_org_id() != org.id):
        return False
    return db.scalar(select(OrganizationMember.id).where(
        OrganizationMember.organization_id == org.id,
        OrganizationMember.user_id == user_id,
        OrganizationMember.active.is_(True),
        OrganizationMember.member_role.in_(['owner', 'manager'])).limit(1)) is not None

# Finance staff can use finance screens; they cannot submit medical waste,
# mutate treatment proofs or operate a vehicle on behalf of the company.
MEMBER_ACTIONS = {
    'waste_read': frozenset({'owner', 'manager', 'dispatcher', 'worker'}),
    'waste_write': frozenset({'owner', 'manager', 'worker'}),
    'pickup_write': frozenset({'owner', 'manager', 'dispatcher', 'worker'}),
    'facility_receive': frozenset({'owner', 'manager', 'worker'}),
    'facility_process': frozenset({'owner', 'manager', 'worker'}),
    'tracking_read': frozenset({'owner', 'manager', 'dispatcher', 'driver', 'worker'}),
    'fleet_operate': frozenset({'owner', 'manager', 'dispatcher', 'driver'}),
    'finance_read': frozenset({'owner', 'manager', 'finance'}),
    'finance_manage': frozenset({'owner', 'manager', 'finance'}),
    'profile_manage': frozenset({'owner', 'manager'}),
}


def can_profile_action(db: Session, profile, user_id, org_type: str, action: str) -> bool:
    """Membership AND capability required for each linked company profile."""
    if profile is None or action not in MEMBER_ACTIONS:
        return False
    org_id = getattr(profile, 'organization_id', None)
    if org_id is None:
        # Legacy unlinked profiles: preserve direct owner's old workflow.
        return profile.user_id == user_id
    if selected_org_id() is not None and selected_org_id() != org_id:
        return False
    member_role = db.scalar(select(OrganizationMember.member_role).where(
        OrganizationMember.organization_id == org_id,
        OrganizationMember.user_id == user_id,
        OrganizationMember.active.is_(True)).limit(1))
    return member_role in MEMBER_ACTIONS[action]


def profile_for_user(db: Session, user_id, org_type: str):
    """Shared member-aware resolver for tracking, analytics and HTTP services."""
    if org_type == 'HOSPITAL':
        from app.repositories.hospital_repository import HospitalRepository
        return HospitalRepository(db).get_by_user_id(user_id)
    if org_type == 'TREATMENT_FACILITY':
        from app.repositories.facility_repository import FacilityRepository
        return FacilityRepository(db).get_by_user_id(user_id)
    return None
