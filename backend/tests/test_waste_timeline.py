HOSPITAL_USER = {
    "email": "timeline-reporter@stalbans.example",
    "password": "CorrectHorseBattery123",
    "full_name": "Timeline Reporter",
    "role": "hospital",
}
HOSPITAL_PROFILE = {
    "name": "St. Alban's General Hospital",
    "registration_number": "HRN-48219",
    "contact_person": "Timeline Reporter",
    "phone": "+1-555-0134",
    "address_line": "400 Alban Way",
    "city": "Rivermill",
    "region": "Rivermill County",
    "postal_code": "48210",
    "bed_count": 220,
}
COLLECTOR_USER = {
    "email": "timeline-collector@greenhaul.example",
    "password": "CorrectHorseBattery123",
    "full_name": "Timeline Collector",
    "role": "collector",
}


def _setup_hospital(client):
    client.post("/api/v1/auth/register", json=HOSPITAL_USER)
    client.post("/api/v1/hospitals/me", json=HOSPITAL_PROFILE)


def _login_hospital(client):
    client.cookies.clear()
    client.post(
        "/api/v1/auth/login",
        json={"email": HOSPITAL_USER["email"], "password": HOSPITAL_USER["password"]},
    )


def _all_category_ids(client):
    return {c["code"]: c["id"] for c in client.get("/api/v1/waste/categories").json()}


def test_reporting_waste_creates_reported_event(client):
    _setup_hospital(client)
    ids = _all_category_ids(client)
    record = client.post(
        "/api/v1/waste", json={"category_id": ids["GENERAL"], "quantity": "5", "unit": "kg"}
    ).json()

    resp = client.get(f"/api/v1/waste/{record['id']}/timeline")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "reported"
    assert events[0]["status_snapshot"] == "reported"
    assert events[0]["actor"]["full_name"] == "Timeline Reporter"
    assert events[0]["quantity"] == "5.00"


def test_classification_and_risk_assessment_append_events_in_order(client):
    _setup_hospital(client)
    ids = _all_category_ids(client)
    record = client.post(
        "/api/v1/waste", json={"category_id": ids["GENERAL"], "quantity": "5", "unit": "kg"}
    ).json()
    client.post(
        f"/api/v1/waste/{record['id']}/classifications/override",
        json={"category_id": ids["GENERAL"]},
    )
    client.post(
        f"/api/v1/waste/{record['id']}/risk-assessments/override",
        json={"risk_level": "low", "suggested_handling": "dispose"},
    )

    events = client.get(f"/api/v1/waste/{record['id']}/timeline").json()
    types = [e["event_type"] for e in events]
    assert types == ["reported", "classified", "risk_assessed"]
    # Chronological order — oldest first, a readable top-to-bottom timeline.
    timestamps = [e["created_at"] for e in events]
    assert timestamps == sorted(timestamps)


def test_running_classification_without_confirming_does_not_log_event(client):
    _setup_hospital(client)
    ids = _all_category_ids(client)
    record = client.post(
        "/api/v1/waste",
        json={"category_id": ids["GENERAL"], "quantity": "5", "unit": "kg", "description": "plain waste"},
    ).json()
    client.post(f"/api/v1/waste/{record['id']}/classifications/run")

    events = client.get(f"/api/v1/waste/{record['id']}/timeline").json()
    assert len(events) == 1  # only "reported" — the unconfirmed run isn't logged
    assert events[0]["event_type"] == "reported"


def test_pickup_lifecycle_appends_events(operation):
    from tests.workflow_support import body, report, request_pickup, start, collect
    s=operation;report(s);request_pickup(s);start(s);collect(s)
    events=body(s.hospital.get(f"/api/v1/waste/{s.record['id']}/timeline"))
    types=[e['event_type'] for e in events]
    assert types[0]=='reported' and 'matched' in types and 'pickup_assigned' in types
    assert types[-1]=='collected' and events[-1]['actor']['full_name']=='Integration collector'


def test_cancelled_pickup_logs_cancellation_event(operation):
    from tests.workflow_support import body, report, request_pickup
    s=operation;report(s);request_pickup(s)
    body(s.hospital.post(f"/api/v1/pickups/{s.pickup['id']}/cancel",json={'reason':'Hospital changed collection plans'}))
    events=body(s.hospital.get(f"/api/v1/waste/{s.record['id']}/timeline"))
    assert events[-1]['event_type']=='pickup_cancelled' and events[-1]['status_snapshot']=='risk_assessed'


def test_matching_confirmation_logs_matched_event(operation):
    from tests.workflow_support import body, report
    s=operation;report(s)
    events=body(s.hospital.get(f"/api/v1/waste/{s.record['id']}/timeline"))
    assert events[-1]['event_type']=='matched'
    assert events[-1]['event_metadata']['destination_name']=='Integration Treatment Facility'


def test_timeline_requires_hospital_ownership(client):
    _setup_hospital(client)
    ids = _all_category_ids(client)
    record = client.post(
        "/api/v1/waste", json={"category_id": ids["GENERAL"], "quantity": "5", "unit": "kg"}
    ).json()

    client.cookies.clear()
    other = {**HOSPITAL_USER, "email": "other-timeline@stalbans.example"}
    client.post("/api/v1/auth/register", json=other)
    client.post("/api/v1/hospitals/me", json=HOSPITAL_PROFILE)

    resp = client.get(f"/api/v1/waste/{record['id']}/timeline")
    assert resp.status_code == 404
