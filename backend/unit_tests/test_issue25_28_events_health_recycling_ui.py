"""Focused regression checks for Issue 25-28 (isolated SQLite)."""
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.health import router as health_router
from app.core.db import get_db
from app.core.config import Settings
from app.models.route import Route, RouteStopStatus, RouteDestinationState
from app.models.business import RecyclingSale, RecyclingAllocation, RecyclingSaleLot
from app.models.audit_log import AuditLog
from app.services.tracking_service import TrackingService
from unit_tests.test_issue12_13_gps_realtime import setup_route
from unit_tests.test_issue14_15_workflow_recycling import (
    db, seeded_sale, payload, new_user,
)
from app.models.roles import UserRole
from app.api.business import (
    admin_recycling_eligible_batches, admin_recycling_sales,
    admin_record_recycling_sale, confirm_recycling_sale, VerifySale,
)


def test_db_readiness_failure_returns_503_not_leaking_credentials():
    app = FastAPI()
    app.include_router(health_router, prefix='/api/v1')
    class DownDatabase:
        def execute(self, *args, **kwargs):
            raise OSError('PASSWORD=hunter2 host=secret.internal dbname=private')
    app.dependency_overrides[get_db] = lambda: DownDatabase()
    with TestClient(app) as client:
        result = client.get('/api/v1/health/db')
    assert result.status_code == 503
    assert result.json()['detail']['database'] == 'unreachable'
    assert 'hunter2' not in result.text and 'secret.internal' not in result.text
    assert result.json()['detail']['message'] == 'Database is unavailable'


def test_db_readiness_healthy_returns_200():
    app = FastAPI()
    app.include_router(health_router, prefix='/api/v1')
    class GoodDatabase:
        def execute(self, *args, **kwargs):
            return None
    app.dependency_overrides[get_db] = lambda: GoodDatabase()
    with TestClient(app) as client:
        result = client.get('/api/v1/health/db')
    assert result.status_code == 200
    assert result.json()['database'] == 'reachable'


def _trip_with_destination():
    engine, database, driver, vehicle, tracking, stop = setup_route()
    route = database.get(Route, tracking.current_route_id)
    stop.status = RouteStopStatus.COLLECTED
    route.destination_state = RouteDestinationState.COLLECTION.value
    route.destination_latitude = Decimal('22.81')
    route.destination_longitude = Decimal('89.55')
    database.commit()
    return engine, database, driver, vehicle, tracking, route


def test_failed_route_progress_commit_never_publishes_uncommitted_state():
    engine, database, driver, vehicle, tracking, route = _trip_with_destination()
    try:
        service = TrackingService(database, Settings(database_url='sqlite+pysqlite:///:memory:'))
        with patch('app.realtime.tracking_manager.tracking_manager.broadcast_from_sync') as broadcast:
            with patch.object(database, 'commit', side_effect=RuntimeError('DB commit rejected')):
                with pytest.raises(RuntimeError, match='DB commit rejected'):
                    service._advance_route_progress(tracking, 22.81, 89.55)
            assert broadcast.call_count == 0
        database.refresh(route)
        assert route.destination_state == RouteDestinationState.COLLECTION.value
    finally:
        database.close(); engine.dispose()


def test_successful_route_progress_commit_precedes_notifications():
    engine, database, driver, vehicle, tracking, route = _trip_with_destination()
    try:
        service = TrackingService(database, Settings(database_url='sqlite+pysqlite:///:memory:'))
        observed = []
        def callback(event, topics):
            observed.append((event, database.get(Route, route.id).destination_state))
        with patch('app.realtime.tracking_manager.tracking_manager.broadcast_from_sync', side_effect=callback):
            service._advance_route_progress(tracking, 22.81, 89.55)
        assert any(x[0]['event'] == 'vehicle.destination.arrived' for x in observed)
        assert all(x[1] == RouteDestinationState.AT_DESTINATION.value for x in observed)
    finally:
        database.close(); engine.dispose()


def test_admin_recycling_candidate_filter_and_sale_allocation(db):
    admin, facility_user, org, fac, hospitals, records, proofs = seeded_sale(db)
    candidates = admin_recycling_eligible_batches(org.id, admin, db)
    assert {item['id'] for item in candidates} == {str(row.id) for row in records}
    assert all(Decimal(row['received_kg']) > 0 for row in candidates)
    assert all(row['hospital_name'] for row in candidates)
    created = admin_record_recycling_sale(payload(org, records), admin, db)
    assert db.get(RecyclingSale, created['id']) is not None
    assert db.scalar(select(AuditLog).where(AuditLog.action == 'recycling.sale.created')).details['created_by_admin']
    assert admin_recycling_eligible_batches(org.id, admin, db) == []
    listing = admin_recycling_sales(admin, db)
    assert len(listing) == 1 and len(listing[0]['lots']) == 2
    assert listing[0]['allocations'] == []
    assert any(event['action'] == 'recycling.sale.created' for event in listing[0]['audit_history'])
    confirm_recycling_sale(created['id'], VerifySale(bank_receipt_reference='test-receipt-123'), admin, db)
    listing = admin_recycling_sales(admin, db)
    assert len(listing[0]['allocations']) == 2
    assert any(event['action'] == 'recycling.sale.receipt_attested' for event in listing[0]['audit_history'])
    assert sum(a['hospital_credit_bdt'] for a in listing[0]['allocations']) == Decimal('900.00')


def test_facility_sale_creation_still_requires_active_membership(db):
    admin, facility_user, org, fac, hospitals, records, proofs = seeded_sale(db)
    outsider = new_user(db, 'random-'+uuid.uuid4().hex[:8], UserRole.FACILITY)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        admin_record_recycling_sale(payload(org, records), outsider, db)
    assert exc.value.status_code == 403


def test_admin_recycling_endpoints_reject_non_admin_http(db):
    from app.api.deps import get_current_user
    from app.api.router import api_router
    hospital = new_user(db, 'finance-hospital-'+uuid.uuid4().hex[:6], UserRole.HOSPITAL)
    from fastapi import FastAPI
    app = FastAPI(); app.include_router(api_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: hospital
    with TestClient(app) as client:
        assert client.get('/api/v1/admin/recycling/sales').status_code == 403
        assert client.get('/api/v1/admin/recycling/eligible-batches', params={'facility_org_id':str(uuid.uuid4())}).status_code == 403
        assert client.post('/api/v1/admin/recycling/sales', json={}).status_code == 403


def test_admin_recycling_full_api_workflow(db):
    from app.api.deps import get_current_user
    from app.api.router import api_router
    admin, facility_user, org, fac, hospitals, records, proofs = seeded_sale(db)
    app = FastAPI(); app.include_router(api_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as client:
        resp = client.get('/api/v1/admin/recycling/eligible-batches', params={'facility_org_id':str(org.id)})
        assert resp.status_code == 200, resp.text
        assert len(resp.json()) == 2
        body = payload(org, records).model_dump(mode='json')
        resp = client.post('/api/v1/admin/recycling/sales', json=body)
        assert resp.status_code == 201, resp.text
        sale_id = resp.json()['id']
        listing = client.get('/api/v1/admin/recycling/sales')
        assert listing.status_code == 200
        assert listing.json()[0]['lots'] and listing.json()[0]['audit_history']
        resp = client.post(f'/api/v1/admin/recycling/sales/{sale_id}/confirm-receipt',
            json={'bank_receipt_reference':'verified-demo-ref-001'})
        assert resp.status_code == 200, resp.text
        assert len(resp.json()['allocations']) == 2
        assert client.post(f'/api/v1/admin/recycling/sales/{sale_id}/confirm-receipt',
            json={'bank_receipt_reference':'verified-demo-ref-001'}).status_code == 409
        listing = client.get('/api/v1/admin/recycling/sales').json()
        assert listing[0]['sale_payment_verified'] is True
        assert len(listing[0]['allocations']) == 2
        assert len(listing[0]['audit_history']) >= 2
