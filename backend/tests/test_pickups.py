"""Current collection requirements: approved destination, route, QR and weight."""
from tests.workflow_support import body, report, request_pickup, start, collect


def test_verified_collector_can_register_and_list_vehicles(operation):
    s=operation
    vehicles=body(s.collector.get('/api/v1/vehicles/mine'))
    assert vehicles[0]['id']==s.vehicle['id'] and vehicles[0]['status']=='available'


def test_hospital_cannot_register_vehicle(operation):
    assert operation.hospital.post('/api/v1/vehicles',json={'vehicle_code':'FORGED','capacity_kg':'500'}).status_code==403


def test_pickup_requires_confirmed_destination(operation):
    s=operation;report(s,match=False)
    assert s.hospital.post('/api/v1/pickups',json={'waste_record_ids':[s.record['id']]}).status_code==409


def test_auto_assignment_reserves_vehicle(operation):
    s=operation;report(s);pickup=request_pickup(s)
    assert pickup['status']=='assigned' and pickup['assigned_vehicle']['id']==s.vehicle['id']
    assert body(s.collector.get('/api/v1/vehicles/mine'))[0]['status']=='reserved'


def test_no_active_vehicle_leaves_pickup_queued(operation):
    s=operation
    body(s.collector.patch(f"/api/v1/vehicles/{s.vehicle['id']}",json={'is_active':False}))
    report(s);pickup=request_pickup(s)
    assert pickup['status']=='requested' and pickup['assigned_vehicle'] is None


def test_duplicate_active_pickup_is_rejected(operation):
    s=operation;report(s);request_pickup(s)
    assert s.hospital.post('/api/v1/pickups',json={'waste_record_ids':[s.record['id']]}).status_code==409


def test_cancellation_releases_reservation(operation):
    s=operation;report(s);request_pickup(s)
    body(s.hospital.post(f"/api/v1/pickups/{s.pickup['id']}/cancel",json={'reason':'Hospital rescheduled this collection'}))
    assert body(s.collector.get('/api/v1/vehicles/mine'))[0]['status']=='available'
    assert body(s.hospital.get(f"/api/v1/waste/{s.record['id']}"))['status']=='risk_assessed'


def test_collection_requires_handover_payload(operation):
    s=operation;report(s);request_pickup(s)
    assert s.collector.post(f"/api/v1/pickups/{s.pickup['id']}/collect").status_code==422


def test_qr_and_weight_do_not_replace_verified_arrival(operation):
    s=operation;report(s);request_pickup(s);start(s)
    qr=body(s.hospital.get(f"/api/v1/pickups/{s.pickup['id']}/handover-qr"))['handover_qr']
    assert s.collector.post(f"/api/v1/pickups/{s.pickup['id']}/collect",json={'handover_qr':qr,'actual_weight_kg':'10','packaging_condition':'sealed'}).status_code==409


def test_verified_handover_keeps_vehicle_on_route(operation):
    s=operation;report(s);request_pickup(s);start(s)
    assert collect(s)['status']=='collected'
    assert body(s.collector.get('/api/v1/vehicles/mine'))[0]['status']=='on_route'


def test_collected_pickup_cannot_be_cancelled(operation):
    s=operation;report(s);request_pickup(s);start(s);collect(s)
    assert s.hospital.post(f"/api/v1/pickups/{s.pickup['id']}/cancel",json={}).status_code==409


def test_dispatched_batch_cannot_regress_to_classification(operation):
    s=operation;report(s);request_pickup(s)
    assert s.hospital.post(f"/api/v1/waste/{s.record['id']}/classifications/override",json={'category_id':s.categories['SHARPS']}).status_code==409
    assert body(s.hospital.get(f"/api/v1/waste/{s.record['id']}"))['status']=='pickup_assigned'
