"""SQLite-only fast regression checks for the 2026-10-10 professional demo patch.

Run from backend directory:
    python checks/verify_professional_upgrade.py
Tests DO NOT modify the developer PostgreSQL database and do not require
FastAPI application startup, Redis, GPS hardware or Next.js.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uuid
from datetime import date, timedelta

os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///:memory:'

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import Base
from app import models
from app.models.user import User
from app.models.roles import UserRole
from app.models.business import Organization, OrganizationMember, OrganizationPermit
from app.models.hospital_profile import HospitalProfile
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.vehicle import Vehicle
from app.models.waste_enums import VehicleStatus
from app.repositories.hospital_repository import HospitalRepository
from app.services.organization_context import select_organization, reset_organization
from app.services.organization_eligibility import can_profile_action, profile_organization
from app.services.business_finance import permits_current, operator_accepts_new_work
from app.realtime.tracking_authorization import can_view_vehicle
from app.services.route_optimization_service import OSRMRoutingProvider, HaversineRoutingProvider, Point
from unittest.mock import patch


def fresh_user(role, tag):
    return User(email=f'{tag}@example.invalid', full_name=tag,
                hashed_password='not-used-in-tests', role=role)


def main():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    assertions = 0
    with Session(engine) as db:
        owner = fresh_user(UserRole.HOSPITAL, 'hospital-owner')
        finance = fresh_user(UserRole.HOSPITAL, 'hospital-finance')
        worker = fresh_user(UserRole.HOSPITAL, 'hospital-worker')
        outsider = fresh_user(UserRole.HOSPITAL, 'hospital-outsider')
        collector = fresh_user(UserRole.COLLECTOR, 'collector')
        db.add_all([owner, finance, worker, outsider, collector]);db.flush()
        h1 = Organization(name='Hospital A', org_type='HOSPITAL', owner_user_id=owner.id, status='verified')
        h2 = Organization(name='Hospital B', org_type='HOSPITAL', owner_user_id=owner.id, status='verified')
        c1 = Organization(name='Transport A', org_type='COLLECTION_COMPANY', owner_user_id=collector.id, status='verified')
        db.add_all([h1,h2,c1]);db.flush()
        db.add_all([
            OrganizationMember(organization_id=h1.id, user_id=owner.id, member_role='owner'),
            OrganizationMember(organization_id=h2.id, user_id=owner.id, member_role='owner'),
            OrganizationMember(organization_id=h1.id, user_id=finance.id, member_role='finance'),
            OrganizationMember(organization_id=h1.id, user_id=worker.id, member_role='worker'),
            OrganizationMember(organization_id=c1.id, user_id=collector.id, member_role='driver'),
        ])
        def hp(org, label):
            return HospitalProfile(user_id=owner.id, organization_id=org.id, name=label,
              registration_number=label, contact_person=label, phone='0',
              address_line=label, city='Khulna', region='Khulna', postal_code='9000')
        p1=hp(h1,'Hospital A');p2=hp(h2,'Hospital B')
        db.add_all([p1,p2]);db.flush()
        repository = HospitalRepository(db)
        assert repository.get_by_user_id(owner.id) is None  # must choose an org
        assertions+=1
        token=select_organization(str(h1.id))
        try:
            assert repository.get_by_user_id(owner.id).id == p1.id
            assert repository.get_by_user_id(worker.id).id == p1.id
            assert repository.get_by_user_id(finance.id).id == p1.id
            assert repository.get_by_user_id(outsider.id) is None
            assert can_profile_action(db,p1,finance.id,'HOSPITAL','finance_read')
            assert not can_profile_action(db,p1,finance.id,'HOSPITAL','waste_write')
            assert can_profile_action(db,p1,worker.id,'HOSPITAL','waste_write')
            assert not can_profile_action(db,p1,worker.id,'HOSPITAL','profile_manage')
            assert not can_profile_action(db,p2,worker.id,'HOSPITAL','waste_read')
            assertions+=9
        finally:reset_organization(token)
        token=select_organization(str(h2.id))
        try:
            assert repository.get_by_user_id(owner.id).id == p2.id
            assert repository.get_by_user_id(worker.id) is None
            assertions+=2
        finally:reset_organization(token)
        today=date.today()
        db.add_all([
            OrganizationPermit(organization_id=c1.id,permit_type='Transport license',reference='OLD', approval_status='approved',expires_on=today-timedelta(days=1)),
            OrganizationPermit(organization_id=c1.id,permit_type='Transport license',reference='NEW', approval_status='approved',expires_on=today+timedelta(days=365)),
            OrganizationPermit(organization_id=c1.id,permit_type='Transport license',reference='PENDING', approval_status='pending',expires_on=today+timedelta(days=730)),
        ]);db.flush()
        assert permits_current(db,c1.id,today)
        assert operator_accepts_new_work(db,c1.id,today)  # 5 free jobs
        assertions+=2
        extra=OrganizationPermit(organization_id=c1.id,permit_type='Environmental permit',reference='DECLINED',approval_status='rejected',expires_on=today+timedelta(days=100))
        db.add(extra);db.flush()
        assert not permits_current(db,c1.id,today)
        extra.approval_status='approved';db.flush()
        assert permits_current(db,c1.id,today)
        assertions+=2
        truck=Vehicle(vehicle_code='KH-TEST-001',assigned_collector_id=collector.id,
                      organization_id=c1.id,capacity_kg=100, status=VehicleStatus.AVAILABLE)
        db.add(truck);db.flush()
        assert can_view_vehicle(db,collector,truck.id)
        member = db.scalar(select(OrganizationMember).where(
            OrganizationMember.user_id==collector.id,
            OrganizationMember.organization_id==c1.id))
        member.active=False;db.flush()
        assert not can_view_vehicle(db,collector,truck.id)
        assert not can_view_vehicle(db,outsider,truck.id)
        assertions+=3
        print(f'PASS: {assertions} SQLite regression assertions (profiles, membership, permit renewal, tracking access)')
    engine.dispose()
    routing = OSRMRoutingProvider('http://unreachable.invalid', 1, HaversineRoutingProvider(25))
    stops = [Point(22.82, 89.55), Point(22.83, 89.56)]
    with patch.object(routing, '_get_json', return_value={'code':'Ok','distances':[[0,None],[1500,0]]}):
        try:
            routing.matrix(stops)
            raise AssertionError('Unreachable OSRM stop was incorrectly treated as zero distance')
        except RuntimeError as exc:
            assert 'unreachable' in str(exc)
            assertions += 1
    print(f'PASS: {assertions} total regression assertions, including OSRM unreachable-stop rejection')

if __name__=='__main__':
    main()
