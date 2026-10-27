"""Regression checks: cancelled-stop receipt completion and atomic signed GPS."""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
import json
import uuid

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models.pickup_request import PickupRequest
from app.models.route import Route, RouteStatus, RouteStop, RouteStopStatus
from app.models.tracking import GPSDeviceNonce, TrackingLocation, TrackingSessionStatus
from app.models.vehicle import Vehicle
from app.models.waste_enums import PickupStatus, VehicleStatus, WasteStatus
from app.schemas.tracking import GPSLocationCreate
from app.models.tracking import LocationSource
from app.services.receiving_service import ReceivingService
from app.services.tracking_service import TrackingService
from unit_tests.test_issue1_pickup_delivery_completion import db, setup_route, receive
from unit_tests.test_issue12_13_gps_realtime import setup_route as setup_gps_route, signed


def test_cancelled_stop_does_not_hold_collected_delivery_active(db):
    route, vehicle, pickups, records, tracking, _ = setup_route(
        db, weights=(2, 3), with_tracking=True
    )
    stopped = db.scalar(select(RouteStop).where(RouteStop.route_id == route.id,
                                             RouteStop.pickup_id == pickups[1].id))
    stopped.status = RouteStopStatus.CANCELLED
    pickups[1].status = PickupStatus.CANCELLED
    records[1].status = WasteStatus.PICKUP_ASSIGNED
    db.commit()

    finished_routes, finished_pickups = receive(db, records[0])
    assert len(finished_pickups) == 1
    assert [r.id for r, _ in finished_routes] == [route.id]
    assert pickups[0].status == PickupStatus.COMPLETED
    assert pickups[1].status == PickupStatus.CANCELLED
    assert route.status == RouteStatus.COMPLETED
    assert vehicle.status == VehicleStatus.AVAILABLE
    assert tracking.status == TrackingSessionStatus.COMPLETED


def test_partial_receipt_still_waits_with_cancelled_stop(db):
    route, vehicle, pickups, records, _, _ = setup_route(db, weights=(1, 1))
    second = db.scalar(select(RouteStop).where(RouteStop.pickup_id == pickups[1].id))
    second.status = RouteStopStatus.CANCELLED
    pickups[1].status = PickupStatus.CANCELLED
    records[1].status = WasteStatus.PICKUP_ASSIGNED
    # The collected pickup has another unreceived batch.
    from app.models.waste_record import WasteRecord
    from app.models.pickup_request import PickupRequestItem
    from app.models.waste_enums import WasteUnit
    extra = WasteRecord(id=uuid.uuid4(), waste_code='MW-29-'+uuid.uuid4().hex[:10],
        hospital_id=pickups[0].hospital_id, category_id=uuid.uuid4(),
        quantity=Decimal('1'), unit=WasteUnit.KG, status=WasteStatus.IN_TRANSIT,
        generated_at=datetime.now(timezone.utc))
    pickups[0].items.append(PickupRequestItem(waste_record=extra))
    db.add(extra); db.commit()
    completed_routes, _ = receive(db, records[0])
    assert completed_routes == []
    assert route.status == RouteStatus.ACTIVE


def test_mismatched_cancellation_cannot_release_vehicle(db):
    route, vehicle, pickups, records, _, _ = setup_route(db, weights=(1, 1))
    stop = db.scalar(select(RouteStop).where(RouteStop.pickup_id == pickups[1].id))
    stop.status = RouteStopStatus.CANCELLED
    # Pickup cancellation missing: must not treat as terminal.
    completed_routes, _ = receive(db, records[0])
    assert completed_routes == []
    assert route.status == RouteStatus.ACTIVE
    assert vehicle.status == VehicleStatus.ON_ROUTE


def test_cancelled_pickup_with_in_transit_waste_blocks_completion(db):
    route, vehicle, pickups, records, _, _ = setup_route(db, weights=(1, 1))
    stop = db.scalar(select(RouteStop).where(RouteStop.pickup_id == pickups[1].id))
    stop.status = RouteStopStatus.CANCELLED
    pickups[1].status = PickupStatus.CANCELLED
    # Consistency guard: physically transported batch cannot disappear.
    completed_routes, _ = receive(db, records[0])
    assert completed_routes == []
    assert route.status == RouteStatus.ACTIVE


def _signed_case():
    engine, database, user, vehicle, tracking, stop = setup_gps_route()
    device = uuid.uuid4()
    secret = bytes.fromhex('ac' * 32)
    settings = Settings(database_url='sqlite+pysqlite:///:memory:',
        gps_trusted_devices_json=json.dumps({str(device): {
            'vehicle_id':str(vehicle.id), 'secret_hex': secret.hex()
        }}))
    data = GPSLocationCreate(latitude=22.81, longitude=89.55,
        timestamp=datetime.now(timezone.utc), accuracy_m=5,
        source=LocationSource.GPS_DEVICE)
    proof = signed(settings, tracking, vehicle, data, secret, device)
    return engine, database, user, vehicle, tracking, stop, settings, data, proof


def test_progression_failure_rolls_back_location_nonce_and_session(monkeypatch):
    eng, db, user, vehicle, tracking, stop, settings, data, proof = _signed_case()
    try:
        initial_last = tracking.last_location_at
        service = TrackingService(db, settings)
        def fail(*args, **kwargs):
            raise RuntimeError('injected route-progress failure')
        monkeypatch.setattr(service, '_advance_route_progress', fail)
        with pytest.raises(RuntimeError, match='route-progress failure'):
            service.record_location(user=user, session_id=tracking.id,
                                    data=data, verified_device=proof)
        db.expire_all()
        assert db.scalar(select(TrackingLocation.id)) is None
        assert db.scalar(select(GPSDeviceNonce.id)) is None
        assert db.get(RouteStop,stop.id).status == RouteStopStatus.EN_ROUTE
        assert db.get(type(tracking), tracking.id).last_location_at == initial_last
        # Retrying the exact same signed report must now succeed.
        saved = TrackingService(db, settings).record_location(
            user=user, session_id=tracking.id, data=data, verified_device=proof)
        assert saved.provenance_verified
        assert db.get(RouteStop,stop.id).status == RouteStopStatus.ARRIVED
    finally:
        db.close(); eng.dispose()


def test_signed_gps_commit_failure_rolls_back_every_component(monkeypatch):
    eng, db, user, vehicle, tracking, stop, settings, data, proof = _signed_case()
    try:
        service = TrackingService(db, settings)
        original_commit = db.commit
        def fail_commit():
            raise RuntimeError('simulated DB commit failure')
        monkeypatch.setattr(db, 'commit', fail_commit)
        with pytest.raises(RuntimeError, match='commit failure'):
            service.record_location(user=user, session_id=tracking.id,
                                    data=data, verified_device=proof)
        monkeypatch.setattr(db, 'commit', original_commit)
        db.expire_all()
        assert db.scalar(select(TrackingLocation.id)) is None
        assert db.scalar(select(GPSDeviceNonce.id)) is None
        assert db.get(RouteStop, stop.id).status == RouteStopStatus.EN_ROUTE
    finally:
        db.close(); eng.dispose()


def test_success_signed_gps_writes_all_state_and_nonce_once():
    eng, db, user, vehicle, tracking, stop, settings, data, proof = _signed_case()
    try:
        saved = TrackingService(db, settings).record_location(
            user=user, session_id=tracking.id, data=data, verified_device=proof)
        db.expire_all()
        assert db.get(TrackingLocation, saved.id) is not None
        assert db.scalar(select(GPSDeviceNonce.id).where(GPSDeviceNonce.nonce == proof.nonce)) is not None
        assert db.get(RouteStop, stop.id).status == RouteStopStatus.ARRIVED
    finally:
        db.close(); eng.dispose()


def test_unsigned_gps_still_records_map_without_advancing():
    eng, db, user, vehicle, tracking, stop, settings, data, proof = _signed_case()
    try:
        loc = TrackingService(db, settings).record_location(
            user=user, session_id=tracking.id, data=data)
        db.expire_all()
        assert db.get(TrackingLocation, loc.id) is not None
        assert db.scalar(select(GPSDeviceNonce.id)) is None
        assert db.get(RouteStop, stop.id).status == RouteStopStatus.EN_ROUTE
    finally:
        db.close(); eng.dispose()
