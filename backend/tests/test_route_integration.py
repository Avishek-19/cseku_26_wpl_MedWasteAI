"""Full route planning against verified destinations and current permissions."""
from datetime import datetime,timezone
from tests.workflow_support import body, report, request_pickup, start


def test_empty_trip_is_rejected(operation):
    s=operation
    assert s.collector.post('/api/v1/routes/optimize',json={'vehicle_id':s.vehicle['id'],'pickup_ids':[]}).status_code==422


def test_ready_route_is_persisted_and_start_is_idempotent(operation):
    s=operation;report(s);request_pickup(s);start(s)
    repeated=body(s.collector.post(f"/api/v1/routes/{s.route['id']}/start"))
    assert repeated['status']=='active' and repeated['tracking_session_id']==s.route['tracking_session_id']


def test_client_cannot_override_verified_destination(operation):
    s=operation;report(s);request_pickup(s)
    result=s.collector.post('/api/v1/routes/optimize',json={'vehicle_id':s.vehicle['id'],
        'pickup_ids':[s.pickup['id']],'origin_latitude':'22.815','origin_longitude':'89.55',
        'destination_latitude':'23.0','destination_longitude':'90.0'})
    assert result.status_code==422


def test_hospital_cannot_start_vehicle_route(operation):
    s=operation;report(s);request_pickup(s);start(s)
    assert s.hospital.post(f"/api/v1/routes/{s.route['id']}/start").status_code==403


def test_unsigned_mobile_location_is_visible_but_cannot_certify_arrival(operation):
    s=operation;report(s);request_pickup(s);start(s)
    location=body(s.collector.post(f"/api/v1/tracking/sessions/{s.route['tracking_session_id']}/locations",json={
        'latitude':'22.820000','longitude':'89.555000','accuracy_m':'5',
        'timestamp':datetime.now(timezone.utc).isoformat(),'source':'mobile_app'}),201)
    assert location['provenance_verified'] is False
    qr=body(s.hospital.get(f"/api/v1/pickups/{s.pickup['id']}/handover-qr"))['handover_qr']
    assert s.collector.post(f"/api/v1/pickups/{s.pickup['id']}/arrive",json={'handover_qr':qr}).status_code==409
