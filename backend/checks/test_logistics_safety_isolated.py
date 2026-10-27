"""Focused SQLite regression tests for safety paths (not a PostgreSQL E2E substitute)."""
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.core.db import Base
from app.core.config import Settings
from app.models.user import User
from app.models.roles import UserRole
from app.models.hospital_profile import HospitalProfile
from app.models.vehicle import Vehicle
from app.models.pickup_request import PickupRequest
from app.models.route import Route, RouteStop, RouteStatus, RouteStopStatus
from app.models.audit_log import AuditLog
from app.models.waste_enums import PickupPriority, PickupStatus, VehicleStatus
from app.rules.pickup_scheduling_rules import compute_scheduled_at
from app.services.pickup_service import PickupNotCollectableError, PickupService
from app.services.route_optimization_service import (
    RouteOptimizationService, HaversineRoutingProvider, StopCandidate, Point, RouteValidationError
)
from app.realtime.tracking_authorization import can_view_vehicle


def utc(yy,mm,dd,hh=0,minute=0):
    return datetime(yy,mm,dd,hh,minute,tzinfo=timezone.utc)


def test_local_09_is_03_utc_and_not_09_utc():
    assert compute_scheduled_at(priority=PickupPriority.NORMAL, now=utc(2026,10,9,4)) == utc(2026,10,10,3)


def test_closed_days_and_holidays_move_to_next_operating_slot():
    result = compute_scheduled_at(priority=PickupPriority.NORMAL, now=utc(2026,10,8,4),
        closed_weekdays=frozenset({4,5}), holidays=frozenset({date(2026,10,11)}))
    assert result == utc(2026,10,12,3)


def test_requested_end_rejects_unfeasible_window():
    with pytest.raises(ValueError, match="No feasible pickup time"):
        compute_scheduled_at(priority=PickupPriority.NORMAL, now=utc(2026,10,9,4),
            requested_at=utc(2026,10,9,7), requested_end_at=utc(2026,10,9,8))
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_scheduled_at(priority=PickupPriority.NORMAL, now=utc(2026,10,9),
            requested_at=datetime(2026,10,10))


def test_emergency_can_use_outside_business_hours():
    assert compute_scheduled_at(priority=PickupPriority.EMERGENCY, now=utc(2026,10,9,1)) == utc(2026,10,9,1)


def test_2opt_destination_is_real_destination_not_last_pickup():
    candidates = [StopCandidate(SimpleNamespace(id=uuid.uuid4()), Point(22.8+i*.01,89.5+i*.01),
                                5, PickupPriority.NORMAL, None) for i in range(3)]
    instance = object.__new__(RouteOptimizationService)
    original = RouteOptimizationService._two_opt
    observed = []
    def capture(order, matrix, stops):
        observed.append(order[:]); return original(order, matrix, stops)
    with patch.object(RouteOptimizationService, '_two_opt', side_effect=capture):
        result = instance._optimize_order(candidates, Point(22.7,89.4), Point(22.99,89.7),
                                          HaversineRoutingProvider(35))
    assert observed[0][0] == 0
    assert observed[0][-1] == len(candidates) + 1
    assert len(result) == len(candidates)
    assert set(id(s.pickup) for s in result) == set(id(s.pickup) for s in candidates)


def fixture_session():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    db = Session(engine)
    def user(role, key):
        u = User(email=f'{key}@example.test',full_name=key,hashed_password='not-real',role=role)
        db.add(u); db.flush(); return u
    driver, admin = user(UserRole.COLLECTOR,'driver'),user(UserRole.ADMIN,'admin')
    huser = user(UserRole.HOSPITAL,'hospital')
    hospital = HospitalProfile(user_id=huser.id,name='Hospital 1',registration_number='reg',
        contact_person='Operator',phone='1234',address_line='Road',city='Khulna',
        region='Khulna',postal_code='9000')
    db.add(hospital);db.flush()
    vehicle = Vehicle(vehicle_code='VEH-1',assigned_collector_id=driver.id,
                      capacity_kg=Decimal('300'),status=VehicleStatus.ON_ROUTE,is_active=True)
    db.add(vehicle);db.flush()
    pickup = PickupRequest(hospital_id=hospital.id,requested_by=huser.id,
        priority=PickupPriority.NORMAL,status=PickupStatus.ASSIGNED,
        assigned_collector_id=driver.id,assigned_vehicle_id=vehicle.id)
    db.add(pickup);db.flush()
    route = Route(vehicle_id=vehicle.id,status=RouteStatus.ACTIVE,version=1,
        destination_state='collection',origin_latitude=Decimal('22.81'),origin_longitude=Decimal('89.55'))
    db.add(route);db.flush()
    stop = RouteStop(route_id=route.id,pickup_id=pickup.id,sequence=1,
        latitude=Decimal('22.81'),longitude=Decimal('89.55'),status=RouteStopStatus.EN_ROUTE)
    db.add(stop);db.commit()
    return engine,db,driver,admin,huser,vehicle,pickup,route,stop


def test_gps_manual_override_requires_independent_admin_approval_and_qr():
    engine,db,driver,admin,_,_,pickup,_,stop = fixture_session()
    service = PickupService(db)
    reason = 'No GPS signal at basement handover'
    with pytest.raises(PickupNotCollectableError):
        service.mark_arrived(collector_id=driver.id, pickup_id=pickup.id,
                             token=pickup.handover_token,manual_reason=reason)
    db.rollback()
    db.add(AuditLog(actor_user_id=admin.id,action='pickup.arrival.exception_approved',
        entity_type='pickup',entity_id=str(pickup.id),
        details={'reason':reason,'route_stop_id':str(stop.id)}))
    db.commit()
    with pytest.raises(PickupNotCollectableError):
        service.mark_arrived(collector_id=driver.id,pickup_id=pickup.id,
                             token='wrong-secret', manual_reason=reason)
    db.rollback()
    verified = service.mark_arrived(collector_id=driver.id,pickup_id=pickup.id,
                                    token=pickup.handover_token,manual_reason=reason)
    assert verified.status == RouteStopStatus.ARRIVED
    assert db.query(AuditLog).filter(AuditLog.action=='pickup.arrival.gps_exception_used').count() == 1
    db.close();engine.dispose()


def test_finished_other_hospital_stops_cannot_leak_through_route_topic():
    engine,db,driver,admin,huser,vehicle,pickup,route,stop = fixture_session()
    other_user=User(email='otherh@example.test',full_name='Other hospital',hashed_password='x',role=UserRole.HOSPITAL)
    db.add(other_user);db.flush()
    other_hospital=HospitalProfile(user_id=other_user.id,name='Other hospital',registration_number='r',
        contact_person='C',phone='1',address_line='x',city='Khulna',region='Khulna',postal_code='9000')
    db.add(other_hospital);db.flush()
    other_pickup=PickupRequest(hospital_id=other_hospital.id, requested_by=other_user.id,
        priority=PickupPriority.NORMAL,status=PickupStatus.COMPLETED,
        assigned_collector_id=driver.id,assigned_vehicle_id=vehicle.id)
    db.add(other_pickup);db.flush()
    db.add(RouteStop(route_id=route.id,pickup_id=other_pickup.id,sequence=2,
                     latitude=Decimal('22.83'),longitude=Decimal('89.54'),status=RouteStopStatus.COLLECTED))
    db.commit()
    assert not can_view_vehicle(db,db.get(User,huser.id),vehicle.id)
    assert can_view_vehicle(db,db.get(User,admin.id),vehicle.id)
    db.close();engine.dispose()


def test_active_route_not_silently_superseded_by_general_optimizer():
    engine,db,driver,admin,_,vehicle,pickup,route,stop=fixture_session()
    service = RouteOptimizationService(db,Settings(database_url='sqlite+pysqlite:///:memory:',routing_provider='haversine'))
    with pytest.raises(RouteValidationError,match='Active route must use'):
        service.optimize(user=admin,vehicle_id=vehicle.id,pickup_ids=[pickup.id])
    assert db.get(Route,route.id).status == RouteStatus.ACTIVE
    db.close();engine.dispose()


def test_live_reoptimization_does_not_erase_arrived_or_collected_stops():
    engine, db, driver, admin, _, vehicle, pickup, route, first = fixture_session()
    first.status = RouteStopStatus.COLLECTED
    others=[]
    for number in (2,3):
        p = PickupRequest(hospital_id=pickup.hospital_id,requested_by=pickup.requested_by,
            priority=PickupPriority.NORMAL,status=PickupStatus.ASSIGNED,
            assigned_collector_id=driver.id,assigned_vehicle_id=vehicle.id)
        db.add(p);db.flush()
        s=RouteStop(route_id=route.id,pickup_id=p.id,sequence=number,
            latitude=Decimal(f'22.{80+number}'),longitude=Decimal(f'89.{51+number}'),
            status=RouteStopStatus.PENDING)
        db.add(s);others.append((p,s))
    db.commit()
    settings = Settings(database_url='sqlite+pysqlite:///:memory:',routing_provider='haversine')
    service = RouteOptimizationService(db,settings)
    provider = HaversineRoutingProvider(35)
    with patch.object(service,'_get_pickups',return_value=[p for p,_ in others]), \
         patch.object(service,'_weight',return_value=5.), \
         patch.object(service,'_destination',return_value=Point(22.9,89.5)), \
         patch.object(service,'_providers',return_value=(provider,provider)):
        updated = service.recalculate_active(user=admin,route_id=route.id,
            reason='Hospital gate temporarily closed')
    assert updated.id == route.id
    assert updated.status == RouteStatus.ACTIVE
    assert db.get(RouteStop,first.id).status == RouteStopStatus.COLLECTED
    assert db.get(RouteStop,first.id).sequence == 1
    assert sorted(db.get(RouteStop,s.id).sequence for _,s in others) == [2,3]
    assert updated.optimization_details['reoptimizations'][-1]['reason'] == 'Hospital gate temporarily closed'
    db.close();engine.dispose()


def test_cancelling_reserved_pickup_invalidates_ready_route_and_releases_vehicle():
    engine,db,driver,admin,huser,vehicle,pickup,route,stop=fixture_session()
    vehicle.status=VehicleStatus.RESERVED
    route.status=RouteStatus.READY
    stop.status=RouteStopStatus.PENDING
    db.commit()
    cancelled=PickupService(db).cancel_pickup(user_id=huser.id,pickup_id=pickup.id,reason='Hospital no longer needs pickup')
    assert cancelled.status == PickupStatus.CANCELLED
    assert db.get(Route,route.id).status == RouteStatus.CANCELLED
    assert db.get(Vehicle,vehicle.id).status == VehicleStatus.AVAILABLE
    db.close();engine.dispose()


def test_route_start_denies_cancelled_stop_even_if_ready_route_was_not_invalidated():
    engine,db,driver,admin,huser,vehicle,pickup,route,stop=fixture_session()
    vehicle.status=VehicleStatus.RESERVED
    route.status=RouteStatus.READY
    stop.status=RouteStopStatus.PENDING
    pickup.status=PickupStatus.CANCELLED
    db.commit()
    service = RouteOptimizationService(db, Settings(database_url='sqlite+pysqlite:///:memory:'))
    with pytest.raises(RouteValidationError):
        service.start(user=admin,route_id=route.id)
    assert db.get(Route,route.id).status == RouteStatus.READY
    assert db.get(Vehicle,vehicle.id).status == VehicleStatus.RESERVED
    db.close();engine.dispose()
