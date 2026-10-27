"""Transport completion and processing through the current evidence gates."""
from uuid import UUID
from tests.workflow_support import body, report, request_pickup, start, collect, transit, receive
from tests.conftest import TestSessionLocal
from app.services.workflow_orchestrator import run_workflow_batch


def en_route(s):
    report(s);request_pickup(s);start(s);collect(s);transit(s)


def test_transit_requires_collection(operation):
    s=operation;report(s);request_pickup(s)
    assert s.collector.post(f"/api/v1/pickups/{s.pickup['id']}/start-transit").status_code==409


def test_in_transit_is_visible_at_confirmed_facility(operation):
    s=operation;en_route(s)
    records=body(s.facility.get('/api/v1/destinations/incoming'))
    assert any(r['id']==s.record['id'] and r['status']=='in_transit' for r in records)


def test_receipt_requires_physical_arrival_or_independent_exception(operation):
    s=operation;en_route(s)
    assert s.facility.post(f"/api/v1/destinations/{s.record['id']}/receive",json={}).status_code==409


def test_receipt_closes_trip_and_releases_vehicle(operation):
    s=operation;en_route(s);receive(s)
    assert body(s.collector.get('/api/v1/vehicles/mine'))[0]['status']=='available'
    assert body(s.collector.get(f"/api/v1/pickups/{s.pickup['id']}"))['status']=='completed'
    assert body(s.collector.get(f"/api/v1/routes/{s.route['id']}"))['status']=='completed'


def test_receipt_quantity_discrepancy_records_incident(operation):
    s=operation;en_route(s);receive(s,quantity='7')
    incidents=body(s.admin.get('/api/v1/admin/incidents'))
    assert any(x['waste_record_id']==s.record['id'] and x['incident_type']=='weight_discrepancy' for x in incidents)


def test_processing_requires_received_batch(operation):
    s=operation;en_route(s)
    assert s.facility.post(f"/api/v1/processing/{s.record['id']}/start",json={'processing_method':s.match['processing_method']}).status_code==409


def test_treatment_proof_and_completion_are_durable(operation):
    s=operation;en_route(s);receive(s)
    body(s.facility.post(f"/api/v1/processing/{s.record['id']}/start",json={'processing_method':s.match['processing_method']}),201)
    assert s.facility.post(f"/api/v1/processing/{s.record['id']}/complete").status_code==409
    body(s.facility.post(f"/api/v1/processing/{s.record['id']}/proof",json={'proof_note':'Treatment log and processing evidence verified by facility staff.'}))
    body(s.facility.post(f"/api/v1/processing/{s.record['id']}/complete"))
    assert body(s.hospital.get(f"/api/v1/waste/{s.record['id']}"))['status']=='completed'
    assert s.facility.post(f"/api/v1/processing/{s.record['id']}/complete").status_code==409


def test_receipt_notification_survives_processing_before_worker_runs(operation):
    s=operation;en_route(s);receive(s)
    body(s.facility.post(f"/api/v1/processing/{s.record['id']}/start",json={'processing_method':s.match['processing_method']}),201)
    with TestSessionLocal() as db:
        result=run_workflow_batch(db)
        assert result['retry']==0
    notifications=body(s.hospital.get('/api/v1/notifications'))
    assert any('received' in item['title'].lower() for item in notifications['items'])
