"""Regression tests for authenticated GPS trust boundaries and independent handover."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hmac
import json
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import Settings
from app.models.audit_log import AuditLog
from app.models.pickup_request import PickupRequest
from app.models.route import Route, RouteStop, RouteStopStatus
from app.models.tracking import LocationSource, TrackingLocation, GPSAnomalyType
from app.models.user import User
from app.models.roles import UserRole
from app.models.waste_enums import PickupStatus, PickupPriority
from app.api.pickups import ArrivalExceptionRequest, ArrivalExceptionApproval, request_no_gps_arrival
from app.api.admin import pickup_arrival_exception_candidates, DeadLetterRetryRequest
from app.api.business import FacilityReceiptExceptionApprove, VerificationRequest
from app.services.tracking_service import TrackingService
from app.services.active_route_cancellation import reconcile_cancelled_stop
from app.schemas.tracking import GPSLocationCreate
from unit_tests.test_issue12_13_gps_realtime import setup_route, signed
from fastapi import HTTPException


def _signed_device(vehicle):
    device = uuid.uuid4()
    key = bytes.fromhex('a7'*32)
    cfg = Settings(database_url='sqlite+pysqlite:///:memory:', gps_trusted_devices_json=json.dumps({
        str(device): {'vehicle_id': str(vehicle.id), 'secret_hex': key.hex()}
    }))
    return cfg, key, device


def test_browser_gps_cannot_advance_then_signed_point_is_not_poisoned():
    engine, db, user, vehicle, session, stop = setup_route()
    try:
        cfg, key, device = _signed_device(vehicle)
        svc = TrackingService(db, cfg)
        now = datetime.now(timezone.utc)
        forged = GPSLocationCreate(latitude=23.4, longitude=90.4,
            timestamp=now-timedelta(seconds=10), accuracy_m=3, source=LocationSource.MOBILE_APP)
        untrusted = svc.record_location(user=user, session_id=session.id, data=forged)
        assert not untrusted.provenance_verified
        assert db.get(RouteStop,stop.id).status == RouteStopStatus.EN_ROUTE
        arrival = GPSLocationCreate(latitude=22.81, longitude=89.55,
            timestamp=now, accuracy_m=4, source=LocationSource.GPS_DEVICE)
        accepted = svc.record_location(user=user, session_id=session.id, data=arrival,
            verified_device=signed(cfg, session, vehicle, arrival, key, device))
        assert accepted.provenance_verified is True
        assert accepted.anomaly_type is None
        assert db.get(RouteStop,stop.id).status == RouteStopStatus.ARRIVED
    finally:
        db.close(); engine.dispose()


def test_signed_track_uses_last_accepted_signed_point_not_unsigned_or_anomalous():
    engine, db, user, vehicle, session, stop = setup_route()
    try:
        cfg,key,device=_signed_device(vehicle); svc=TrackingService(db,cfg)
        now=datetime.now(timezone.utc)
        def gps(lat,lon,ago,*,trusted):
            item=GPSLocationCreate(latitude=lat,longitude=lon,
                timestamp=now-timedelta(seconds=ago), accuracy_m=5, source=LocationSource.GPS_DEVICE)
            return svc.record_location(user=user,session_id=session.id,data=item,
                verified_device=signed(cfg,session,vehicle,item,key,device) if trusted else None)
        a=gps(22.8,89.54,60,trusted=True)
        assert a.anomaly_type is None
        # A signed but physically impossible jump is stored, but never becomes
        # the speed-validation baseline for the next authenticated point.
        bad=gps(23.4,90.4,40,trusted=True)
        assert bad.anomaly_type is not None
        gps(23.5,90.5,30,trusted=False)
        good=gps(22.80001,89.54001,20,trusted=True)
        assert good.anomaly_type is None
        assert svc.tracking.get_latest_location_for_session(session.id, trusted_only=True).id == good.id
    finally: db.close();engine.dispose()


def _other_stop(db, route, pickup, user, vehicle):
    second=PickupRequest(hospital_id=pickup.hospital_id,requested_by=pickup.requested_by,
        priority=PickupPriority.NORMAL,status=PickupStatus.ASSIGNED,assigned_collector_id=user.id,
        assigned_vehicle_id=vehicle.id)
    db.add(second);db.flush()
    db.add(RouteStop(route_id=route.id,pickup_id=second.id,sequence=2,
        latitude=Decimal('22.82'),longitude=Decimal('89.56'),status=RouteStopStatus.PENDING))
    db.commit()


def test_cancellation_ignores_unsigned_location_as_authoritative_origin():
    engine,db,user,vehicle,session,stop=setup_route()
    try:
        route=db.get(Route,session.current_route_id); pickup=db.get(PickupRequest,stop.pickup_id)
        _other_stop(db,route,pickup,user,vehicle)
        route.tracking_session_id=session.id; db.commit()
        db.add(TrackingLocation(tracking_session_id=session.id,vehicle_id=vehicle.id,
            latitude=Decimal('23.8'),longitude=Decimal('90.8'),
            timestamp=datetime.now(timezone.utc), accuracy_m=Decimal('2'),
            source=LocationSource.MOBILE_APP,provenance_verified=False))
        db.commit()
        reconcile_cancelled_stop(db,route=route,cancelled_stop=stop,vehicle=vehicle,
            pickup=pickup,timestamp=datetime.now(timezone.utc))
        assert float(route.origin_latitude) == pytest.approx(22.81)
        assert float(route.origin_longitude) == pytest.approx(89.55)
    finally:db.close();engine.dispose()


def test_cancellation_uses_recent_accurate_verified_point_not_latest_unsigned():
    engine,db,user,vehicle,session,stop=setup_route()
    try:
        route=db.get(Route,session.current_route_id);pickup=db.get(PickupRequest,stop.pickup_id)
        _other_stop(db,route,pickup,user,vehicle)
        route.tracking_session_id=session.id; db.commit()
        now=datetime.now(timezone.utc)
        db.add_all([
            TrackingLocation(tracking_session_id=session.id,vehicle_id=vehicle.id,
                latitude=Decimal('22.815'),longitude=Decimal('89.555'),timestamp=now-timedelta(seconds=30),
                accuracy_m=Decimal('10'),source=LocationSource.GPS_DEVICE,provenance_verified=True),
            TrackingLocation(tracking_session_id=session.id,vehicle_id=vehicle.id,
                latitude=Decimal('23.8'),longitude=Decimal('90.8'),timestamp=now,
                accuracy_m=Decimal('1'),source=LocationSource.MOBILE_APP,provenance_verified=False),
        ]);db.commit()
        reconcile_cancelled_stop(db,route=route,cancelled_stop=stop,vehicle=vehicle,
            pickup=pickup,timestamp=now)
        assert float(route.origin_latitude)==pytest.approx(22.815)
        assert float(route.origin_longitude)==pytest.approx(89.555)
    finally:db.close();engine.dispose()


@pytest.mark.parametrize('model,minimum',[
    (DeadLetterRetryRequest,12), (ArrivalExceptionApproval,12),
    (ArrivalExceptionRequest,12), (FacilityReceiptExceptionApprove,20),
])
def test_documented_reasons_must_be_meaningful_after_trim(model, minimum):
    for raw in [' '*100, '\t  \n'*10, '  tiny   ']:
        with pytest.raises(ValidationError): model(reason=raw)
    cleaned=model(reason='  '+('x'*minimum)+'  ')
    assert cleaned.reason=='x'*minimum
    with pytest.raises(ValidationError):model(reason='x'*(minimum-1))


def test_verification_request_reason_also_uses_normalized_validation():
    with pytest.raises(ValidationError):
        VerificationRequest(approved=True,reason=' '*40)
    assert VerificationRequest(approved=True,reason='  independently reviewed  ').reason=='independently reviewed'


def test_driver_request_requires_assignment_and_cannot_self_approve():
    engine,db,user,vehicle,session,stop=setup_route()
    try:
        pickup=db.get(PickupRequest,stop.pickup_id)
        payload=ArrivalExceptionRequest(reason='Browser GPS has no secure device certificate')
        result=request_no_gps_arrival(pickup_id=pickup.id,payload=payload,current_user=user,db=db)
        assert result['requested'] is True and result['approved'] is False
        audit=db.scalar(select(AuditLog).where(AuditLog.action=='pickup.arrival.exception_requested'))
        assert audit and audit.actor_user_id==user.id
        assert db.get(RouteStop,stop.id).status==RouteStopStatus.EN_ROUTE
        admin=User(email='admin-candidate@example.test',full_name='Admin',hashed_password='x',role=UserRole.ADMIN)
        db.add(admin);db.commit()
        candidates=pickup_arrival_exception_candidates(current_user=admin,db=db)
        candidate=next(c for c in candidates if c['pickup_id']==str(pickup.id))
        assert candidate['driver_reported_reason']==payload.reason
        assert candidate['driver_requested_at'] is not None
        intruder=User(email='other-col@example.test',full_name='Other',hashed_password='x',role=UserRole.COLLECTOR)
        db.add(intruder);db.commit()
        with pytest.raises(HTTPException) as exc:
            request_no_gps_arrival(pickup_id=pickup.id,payload=payload,current_user=intruder,db=db)
        assert exc.value.status_code==404
    finally:db.close();engine.dispose()
