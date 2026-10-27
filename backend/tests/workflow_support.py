"""Real HTTP workflow fixtures: approved organizations, destinations and handovers.

Only the administrator bootstrap is seeded directly; workflow actions go through
permission-checked API endpoints. Routing is deterministic in automated tests.
"""
import uuid
from types import SimpleNamespace
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.core.security import hash_password, create_access_token
from app.models.user import User
from app.models.roles import UserRole
from tests.conftest import TestSessionLocal

PASSWORD='CorrectHorseBattery123'
REASON='Supervisor independently confirmed physical vehicle arrival and site handover.'


def body(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def make_operation(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),'routing_provider','haversine')
    clients={role:TestClient(app,base_url='http://localhost') for role in ('hospital','collector','facility','admin')}
    with TestSessionLocal() as db:
        admin=User(email=f'admin-{uuid.uuid4().hex}@example.org',full_name='Independent Supervisor',
                   hashed_password=hash_password(PASSWORD),role=UserRole.ADMIN,is_active=True)
        db.add(admin);db.commit();admin_id=admin.id
    clients['admin'].cookies.set('mw_session',create_access_token(user_id=admin_id,role='admin'),domain='localhost.local',path='/')
    s=SimpleNamespace(**clients,orgs={},users={},record=None,pickup=None,route=None,quantity='10')
    for role,kind in [('hospital','HOSPITAL'),('collector','COLLECTION_COMPANY'),('facility','TREATMENT_FACILITY')]:
        c=clients[role]
        user=body(c.post('/api/v1/auth/register',json={'email':f'{role}-{uuid.uuid4().hex}@example.org',
             'password':PASSWORD,'full_name':f'Integration {role}','role':role}),201)
        org=body(c.post('/api/v1/organizations',json={'name':f'Verified {role} organization','org_type':kind}),201)
        permit=body(c.post(f"/api/v1/organizations/{org['id']}/permits",json={
            'permit_type':'Operational permit','reference':f'PERMIT-{uuid.uuid4().hex}'}))
        body(s.admin.post(f"/api/v1/admin/permits/{permit['id']}/review",json={'approved':True,'reason':REASON}))
        body(s.admin.post(f"/api/v1/admin/organizations/{org['id']}/verification",json={'approved':True,'reason':REASON}))
        s.users[role]=user;s.orgs[role]=org
    common={'name':'Integration Hospital','registration_number':'HRN-INTEGRATION','contact_person':'Authorized Staff',
        'phone':'01700000000','address_line':'Hospital Road','city':'Khulna','region':'Khulna',
        'postal_code':'9000','latitude':'22.820000','longitude':'89.555000'}
    s.hospital_profile=body(s.hospital.post('/api/v1/hospitals/me',json=common),201)
    categories=body(s.hospital.get('/api/v1/waste/categories'))
    s.categories={c['code']:c['id'] for c in categories}
    s.facility_profile=body(s.facility.post('/api/v1/facilities/me',json={**common,
        'name':'Integration Treatment Facility','registration_number':'FAC-INTEGRATION','capacity_kg':'5000',
        'latitude':'22.825000','longitude':'89.560000','processing_services':['INCINERATION','FINAL_DISPOSAL','RECYCLING'],
        'accepted_category_ids':list(s.categories.values())}),201)
    body(s.admin.patch(f"/api/v1/admin/verification/facility/{s.facility_profile['id']}?verified=true"))
    s.vehicle=body(s.collector.post('/api/v1/vehicles',json={'vehicle_code':'VAN-INTEGRATION','capacity_kg':'500'}),201)
    return s


def report(s, *, category='GENERAL',quantity='10', match=True):
    s.quantity=quantity
    s.record=body(s.hospital.post('/api/v1/waste',json={'quantity':quantity,'unit':'kg','description':'A reported medical waste batch'}),201)
    assert s.record['category']['code']=='PENDING'
    body(s.hospital.post(f"/api/v1/waste/{s.record['id']}/classifications/override",json={'category_id':s.categories[category]}))
    body(s.hospital.post(f"/api/v1/waste/{s.record['id']}/risk-assessments/override",json={
        'risk_level':'low','suggested_handling':'recycle' if category=='RECYCLABLE' else 'dispose'}))
    if match:
        result=body(s.hospital.post(f"/api/v1/waste/{s.record['id']}/matching/run"),201)
        assert result['candidates']
        s.match=body(s.hospital.post(f"/api/v1/waste/{s.record['id']}/matching/confirm",json={}))
    return s.record


def request_pickup(s):
    s.pickup=body(s.hospital.post('/api/v1/pickups',json={'waste_record_ids':[s.record['id']]}),201)
    return s.pickup


def start(s):
    s.route=body(s.collector.post('/api/v1/routes/optimize',json={'vehicle_id':s.vehicle['id'],
        'pickup_ids':[s.pickup['id']],'origin_latitude':'22.815000','origin_longitude':'89.550000'}),201)
    body(s.collector.post(f"/api/v1/routes/{s.route['id']}/confirm"))
    s.route=body(s.collector.post(f"/api/v1/routes/{s.route['id']}/start"))
    return s.route


def collect(s):
    qr=body(s.hospital.get(f"/api/v1/pickups/{s.pickup['id']}/handover-qr"))['handover_qr']
    body(s.admin.post(f"/api/v1/pickups/{s.pickup['id']}/arrival-exception-approval",json={'reason':REASON}))
    body(s.collector.post(f"/api/v1/pickups/{s.pickup['id']}/arrive",json={'handover_qr':qr,'no_gps_reason':REASON}))
    return body(s.collector.post(f"/api/v1/pickups/{s.pickup['id']}/collect",json={
        'handover_qr':qr,'actual_weight_kg':s.quantity,'packaging_condition':'sealed'}))


def transit(s):
    return body(s.collector.post(f"/api/v1/pickups/{s.pickup['id']}/start-transit"))


def receive(s, *, quantity=None):
    body(s.admin.post(f"/api/v1/admin/waste/{s.record['id']}/receipt-exception",json={'reason':REASON}))
    return body(s.facility.post(f"/api/v1/destinations/{s.record['id']}/receive",json={} if quantity is None else {'received_quantity':quantity}))
