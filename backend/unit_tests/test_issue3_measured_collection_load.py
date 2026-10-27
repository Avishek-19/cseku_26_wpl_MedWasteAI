"""Issue 3: measured load, variance evidence, and atomic handover regression.

Run from backend:
  DATABASE_URL=sqlite+pysqlite:///:memory: python -m pytest -q unit_tests/test_issue3_measured_collection_load.py
Tests exercise the actual PickupService collection method with SQLite; Postgres
concurrent row-lock behavior still needs separate integration verification.
"""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.core.db import Base
from app.models.audit_log import AuditLog
from app.models.collection_proof import CollectionProof
from app.models.incident import Incident
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.route import Route, RouteStatus, RouteStop, RouteStopStatus
from app.models.vehicle import Vehicle
from app.models.waste_enums import (
    IncidentSeverity, PickupPriority, PickupStatus, VehicleStatus, WasteStatus, WasteUnit,
)
from app.models.waste_record import WasteRecord
from app.services.collection_weight_guard import CollectionWeightError, check_collection_load
from app.services.pickup_service import (
    NotAssignedCollectorError, PickupService, PickupWeightValidationError,
)


@pytest.fixture
def db():
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as session:
        yield session
    engine.dispose()


def build_route(db, *, weights=((Decimal('30'), WasteUnit.KG),), capacity='100', statuses=None):
    collector = uuid4()
    vehicle = Vehicle(id=uuid4(), vehicle_code=f'V-{uuid4().hex[:9]}',
                      assigned_collector_id=collector, status=VehicleStatus.ON_ROUTE,
                      capacity_kg=Decimal(capacity), is_active=True)
    db.add(vehicle)
    route = Route(id=uuid4(), vehicle_id=vehicle.id, status=RouteStatus.ACTIVE)
    db.add(route)
    pickups = []
    for i, groups in enumerate(weights):
        # Each pickup's 'groups' can be a tuple of (mass, unit), or a tuple of such pairs.
        batches = [groups] if isinstance(groups[0], Decimal) else groups
        pickup = PickupRequest(id=uuid4(), hospital_id=uuid4(),
                               priority=PickupPriority.NORMAL, status=PickupStatus.ASSIGNED,
                               assigned_vehicle_id=vehicle.id, assigned_collector_id=collector)
        for mass, unit in batches:
            record = WasteRecord(id=uuid4(), waste_code=f'MW-ISSUE3-{uuid4().hex[:8]}',
                                 hospital_id=pickup.hospital_id, category_id=uuid4(),
                                 quantity=mass, unit=unit, status=WasteStatus.PICKUP_ASSIGNED,
                                 generated_at=datetime.now(timezone.utc))
            pickup.items.append(PickupRequestItem(waste_record=record))
            db.add(record)
        db.add(pickup)
        db.add(RouteStop(route_id=route.id, pickup_id=pickup.id, sequence=i + 1,
                         status=(statuses[i] if statuses else
                                 (RouteStopStatus.ARRIVED if i == 0 else RouteStopStatus.PENDING)),
                         latitude=Decimal('22.8'), longitude=Decimal('89.5')))
        pickups.append(pickup)
    db.commit()
    return vehicle, route, pickups, collector


def service_for(db, monkeypatch):
    svc = PickupService(db)
    # Authorization's organization-membership checks are tested separately;
    # these tests still check the concrete pickup's assigned_collector_id.
    monkeypatch.setattr(svc, '_require_active_driver', lambda user, vehicle_id: None)
    from app.realtime.tracking_manager import tracking_manager
    monkeypatch.setattr(tracking_manager, 'broadcast_from_sync', lambda *args, **kw: None)
    return svc


def collect(svc, pickup, collector, weight, *, reason=None, packaging='sealed'):
    return svc.collect_pickup(collector_id=collector, pickup_id=pickup.id,
                              token=pickup.handover_token, actual_weight_kg=Decimal(str(weight)),
                              exception_reason=reason, packaging_condition=packaging)


def test_exact_capacity_two_stops_and_real_proof_persisted(db, monkeypatch):
    vehicle, route, (first, second), actor = build_route(
        db, weights=((Decimal('30'), WasteUnit.KG), (Decimal('70'), WasteUnit.KG)), capacity='100')
    svc = service_for(db, monkeypatch)
    saved = collect(svc, first, actor, '30')
    assert saved.status == PickupStatus.COLLECTED
    assert db.scalar(select(CollectionProof).where(CollectionProof.pickup_id == first.id)).accepted_weight_kg == Decimal('30')
    assert db.get(Vehicle, vehicle.id).status == VehicleStatus.ON_ROUTE
    second_stop = db.scalar(select(RouteStop).where(RouteStop.pickup_id == second.id))
    assert second_stop.status == RouteStopStatus.EN_ROUTE
    second_stop.status = RouteStopStatus.ARRIVED
    db.commit()
    collect(svc, second, actor, '70')
    assert len(db.scalars(select(CollectionProof)).all()) == 2
    assert db.get(Route, route.id).status == RouteStatus.ACTIVE


def test_single_measured_overload_rejected_before_proof_or_pickup_transition(db, monkeypatch):
    _, _, (pickup,), actor = build_route(db, capacity='50')
    svc = service_for(db, monkeypatch)
    with pytest.raises(PickupWeightValidationError, match='exceeds vehicle capacity'):
        collect(svc, pickup, actor, '60', reason='Approved measurement verified')
    db.rollback(); db.expire_all()
    assert db.get(PickupRequest, pickup.id).status == PickupStatus.ASSIGNED
    assert db.scalars(select(CollectionProof)).all() == []
    assert db.scalars(select(Incident)).all() == []


def test_pending_pickup_reservation_is_included_in_capacity_guard(db, monkeypatch):
    _, _, (first, second), actor = build_route(db, weights=((Decimal('40'), WasteUnit.KG),
                                                                (Decimal('60'), WasteUnit.KG)), capacity='100')
    with pytest.raises(PickupWeightValidationError, match='remaining reserved 60.000'):
        collect(service_for(db, monkeypatch), first, actor, '42', reason='Measured a little more')
    db.rollback(); db.expire_all()
    assert db.scalars(select(CollectionProof)).all() == []
    assert db.get(PickupRequest, second.id).status == PickupStatus.ASSIGNED


def test_previous_actual_load_used_instead_of_previous_reported_load(db, monkeypatch):
    _, route, (first, second), actor = build_route(db, weights=((Decimal('40'), WasteUnit.KG),
                                                                (Decimal('50'), WasteUnit.KG)), capacity='100')
    svc = service_for(db, monkeypatch)
    collect(svc, first, actor, '45', reason='Scale calibration checked at pickup')
    second_stop = db.scalar(select(RouteStop).where(RouteStop.pickup_id == second.id))
    second_stop.status = RouteStopStatus.ARRIVED
    db.commit()
    with pytest.raises(PickupWeightValidationError, match='105.000 kg projected'):
        collect(svc, second, actor, '60', reason='Higher than estimate after weighing')
    db.rollback(); db.expire_all()
    assert db.get(Route, route.id).status == RouteStatus.ACTIVE
    assert len(db.scalars(select(CollectionProof)).all()) == 1


def test_discrepancy_5_percent_requires_reason_and_persists_minor_incident(db, monkeypatch):
    _, _, (pickup,), actor = build_route(db, capacity='100')
    svc = service_for(db, monkeypatch)
    with pytest.raises(PickupWeightValidationError, match='at least 5%'):
        collect(svc, pickup, actor, '31.5')
    db.rollback()
    result = collect(svc, pickup, actor, '31.5', reason='Hospital scale calibration note')
    assert result.status == PickupStatus.COLLECTED
    incident = db.scalar(select(Incident))
    assert incident.severity == IncidentSeverity.MINOR
    assert str(pickup.id) in incident.description
    assert db.scalar(select(CollectionProof)).exception_reason == 'Hospital scale calibration note'
    audit = db.scalar(select(AuditLog).where(AuditLog.action == 'pickup.handover.weight_exception'))
    assert audit.details['actual_weight_kg'] == '31.5'


def test_underweight_major_discrepancy_requires_and_records_explanation(db, monkeypatch):
    _, _, (pickup,), actor = build_route(db)
    svc = service_for(db, monkeypatch)
    collect(svc, pickup, actor, '21', reason='Weighed at physical handover station')
    assert db.scalar(select(Incident)).severity == IncidentSeverity.MAJOR
    assert db.scalar(select(CollectionProof)).accepted_weight_kg == Decimal('21')


def test_variance_below_five_percent_needs_no_exception(db, monkeypatch):
    _, _, (pickup,), actor = build_route(db)
    collect(service_for(db, monkeypatch), pickup, actor, '31.2')
    assert db.scalars(select(Incident)).all() == []
    assert db.scalars(select(AuditLog).where(AuditLog.action == 'pickup.handover.weight_exception')).all() == []


def test_exception_packaging_requires_reason_even_without_weight_discrepancy(db, monkeypatch):
    _, _, (pickup,), actor = build_route(db)
    svc = service_for(db, monkeypatch)
    with pytest.raises(PickupWeightValidationError, match='at least 5%'):
        collect(svc, pickup, actor, '30', packaging='exception')
    db.rollback()
    collect(svc, pickup, actor, '30', packaging='exception', reason='Damaged container sealed again')
    assert db.scalar(select(CollectionProof)).packaging_condition == 'exception'
    assert db.scalar(select(AuditLog).where(AuditLog.action == 'pickup.handover.weight_exception'))
    assert db.scalars(select(Incident)).all() == []


def test_multi_batch_pickup_uses_sum_and_lb_conversion(db, monkeypatch):
    _, _, (pickup,), actor = build_route(db, weights=((
        (Decimal('10'), WasteUnit.KG), (Decimal('22.0462262185'), WasteUnit.LB),
    ),), capacity='50')
    # 22.046226... lb ~= 10 kg, so measured 20 kg is not discrepant.
    collect(service_for(db, monkeypatch), pickup, actor, '20')
    assert db.scalars(select(Incident)).all() == []


def test_inconsistent_prior_collected_stop_without_proof_fails_closed(db):
    _, route, (first, second), _ = build_route(db, weights=((Decimal('40'), WasteUnit.KG),
                                                               (Decimal('40'), WasteUnit.KG)), capacity='100')
    db.scalar(select(RouteStop).where(RouteStop.pickup_id == first.id)).status = RouteStopStatus.COLLECTED
    first.status = PickupStatus.COLLECTED
    db.scalar(select(RouteStop).where(RouteStop.pickup_id == second.id)).status = RouteStopStatus.ARRIVED
    db.flush()
    with pytest.raises(CollectionWeightError, match='previous proof'):
        check_collection_load(db, route_id=route.id, pickup_id=second.id,
                              actual_weight_kg=Decimal('40'), capacity_kg=Decimal('100'))


def test_skipped_stop_not_reserved_in_active_route(db):
    _, route, (first, second), _ = build_route(db, weights=((Decimal('50'), WasteUnit.KG),
                                                               (Decimal('60'), WasteUnit.KG)), capacity='100',
                                               statuses=[RouteStopStatus.ARRIVED, RouteStopStatus.SKIPPED])
    load = check_collection_load(db, route_id=route.id, pickup_id=first.id,
                                 actual_weight_kg=Decimal('50'), capacity_kg=Decimal('100'))
    assert load.remaining_reserved_kg == Decimal('0')
    assert load.projected_load_kg == Decimal('50')


@pytest.mark.parametrize('invalid', [Decimal('NaN'), Decimal('Infinity'), Decimal('0'), Decimal('-1')])
def test_nonfinite_and_nonpositive_measurement_fail_closed(db, invalid):
    _, route, (pickup,), _ = build_route(db)
    with pytest.raises(CollectionWeightError, match='finite positive'):
        check_collection_load(db, route_id=route.id, pickup_id=pickup.id,
                              actual_weight_kg=invalid, capacity_kg=Decimal('100'))


def test_fake_driver_is_denied_before_handover(db, monkeypatch):
    _, _, (pickup,), actor = build_route(db)
    svc = service_for(db, monkeypatch)
    with pytest.raises(NotAssignedCollectorError):
        collect(svc, pickup, uuid4(), '30')
    assert db.scalars(select(CollectionProof)).all() == []


def test_db_transaction_rolls_back_weight_proof_and_incident_together(db, monkeypatch):
    _, _, (pickup,), actor = build_route(db)
    svc = service_for(db, monkeypatch)
    def abort(**kwargs):
        raise RuntimeError('injected event store failure')
    monkeypatch.setattr(svc.events, 'record', abort)
    with pytest.raises(RuntimeError, match='injected event store failure'):
        collect(svc, pickup, actor, '40', reason='Weight differs on reweighing')
    db.rollback(); db.expire_all()
    assert db.scalars(select(CollectionProof)).all() == []
    assert db.scalars(select(Incident)).all() == []
    assert db.scalars(select(AuditLog).where(AuditLog.action == 'pickup.handover.weight_exception')).all() == []
    assert db.get(PickupRequest, pickup.id).status == PickupStatus.ASSIGNED


def test_overweight_cannot_be_bypassed_with_exception_packaging_or_reason(db, monkeypatch):
    _, _, (pickup,), actor = build_route(db, capacity='30')
    svc = service_for(db, monkeypatch)
    with pytest.raises(PickupWeightValidationError, match='Unsafe vehicle load'):
        collect(svc, pickup, actor, '90', packaging='exception',
                reason='Dispatcher verbally approved overweight load')
    db.rollback()
    assert db.scalars(select(CollectionProof)).all() == []


def test_unsupported_volume_unit_cannot_be_guessed_into_kg(db):
    _, route, (pickup,), _ = build_route(db, weights=((Decimal('10'), WasteUnit.L),))
    with pytest.raises(CollectionWeightError, match='no valid kg-equivalent'):
        check_collection_load(db, route_id=route.id, pickup_id=pickup.id,
                              actual_weight_kg=Decimal('10'), capacity_kg=Decimal('100'))


def test_missing_route_pickup_rejected_before_weight_estimate(db):
    _, route, (pickup,), _ = build_route(db)
    with pytest.raises(CollectionWeightError, match='not an eligible stop'):
        check_collection_load(db, route_id=route.id, pickup_id=uuid4(),
                              actual_weight_kg=Decimal('10'), capacity_kg=Decimal('100'))


def test_same_pickup_cannot_be_collected_twice(db, monkeypatch):
    from app.services.pickup_service import PickupNotCollectableError
    _, _, (pickup,), actor = build_route(db)
    svc = service_for(db, monkeypatch)
    collect(svc, pickup, actor, '30')
    with pytest.raises(PickupNotCollectableError):
        collect(svc, pickup, actor, '30')
    assert len(db.scalars(select(CollectionProof)).all()) == 1


def test_11_character_discrepancy_explanation_is_not_accepted(db, monkeypatch):
    _, _, (pickup,), actor = build_route(db)
    with pytest.raises(PickupWeightValidationError, match='at least 12 characters'):
        collect(service_for(db, monkeypatch), pickup, actor, '35', reason='elevenchars')
    db.rollback()
    assert db.scalars(select(CollectionProof)).all() == []


def test_api_payload_rejects_impossible_and_overprecise_weights():
    # API module imports bcrypt through its auth deps, which may not be installed
    # in minimal isolated-test environments. Exercise the exact Pydantic class
    # declaration from the API source without importing unrelated auth modules.
    import ast
    from pathlib import Path
    from pydantic import BaseModel, Field, ValidationError
    path = Path(__file__).resolve().parents[1] / 'app' / 'api' / 'pickups.py'
    source = ast.parse(path.read_text())
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'HandoverRequest')
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    scope = {'BaseModel': BaseModel, 'Field': Field, 'Decimal': Decimal, 'str': str}
    exec(compile(module, str(path), 'exec'), scope)
    HandoverRequest = scope['HandoverRequest']
    base = dict(handover_qr='X' * 32, packaging_condition='sealed')
    for invalid in ('-1', '0', '1.0009', 'NaN', 'Infinity'):
        with pytest.raises(ValidationError):
            HandoverRequest(**base, actual_weight_kg=invalid)
    accepted = HandoverRequest(**base, actual_weight_kg='2.125',
                               exception_reason='Reweighed using the backup scale')
    assert accepted.actual_weight_kg == Decimal('2.125')
    assert accepted.exception_reason
