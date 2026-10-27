HOSPITAL_USER = {
    "email": "risk-reporter@stalbans.example",
    "password": "CorrectHorseBattery123",
    "full_name": "Risk Reporter",
    "role": "hospital",
}

HOSPITAL_PROFILE = {
    "name": "St. Alban's General Hospital",
    "registration_number": "HRN-48219",
    "contact_person": "Risk Reporter",
    "phone": "+1-555-0134",
    "address_line": "400 Alban Way",
    "city": "Rivermill",
    "region": "Rivermill County",
    "postal_code": "48210",
    "bed_count": 220,
}


def _setup_hospital(client):
    client.post("/api/v1/auth/register", json=HOSPITAL_USER)
    client.post("/api/v1/hospitals/me", json=HOSPITAL_PROFILE)


def _category_id(client, code):
    categories = client.get("/api/v1/waste/categories").json()
    return next(c["id"] for c in categories if c["code"] == code)


def _create_classified_record(client, *, category_code, quantity="5"):
    category_id = _category_id(client, category_code)
    record = client.post(
        "/api/v1/waste", json={"category_id": category_id, "quantity": quantity, "unit": "kg"}
    ).json()
    client.post(f"/api/v1/waste/{record['id']}/classifications/override", json={"category_id": category_id})
    return record


def test_risk_assessment_requires_classification_first(client):
    _setup_hospital(client)
    category_id = _category_id(client, "GENERAL")
    record = client.post(
        "/api/v1/waste", json={"category_id": category_id, "quantity": "5", "unit": "kg"}
    ).json()

    resp = client.post(f"/api/v1/waste/{record['id']}/risk-assessments/run")
    assert resp.status_code == 409


def test_low_risk_recyclable_category(client):
    _setup_hospital(client)
    record = _create_classified_record(client, category_code="RECYCLABLE", quantity="2")

    resp = client.post(f"/api/v1/waste/{record['id']}/risk-assessments/run")
    assert resp.status_code == 201
    body = resp.json()
    assert body["risk_level"] == "low"
    assert body["recyclability_decision"] is True
    assert body["suggested_handling"] == "recycle"


def test_high_risk_sharps_suggests_treat(client):
    _setup_hospital(client)
    record = _create_classified_record(client, category_code="SHARPS", quantity="5")

    resp = client.post(f"/api/v1/waste/{record['id']}/risk-assessments/run")
    body = resp.json()
    assert body["risk_level"] == "high"
    assert body["recyclability_decision"] is False
    assert body["suggested_handling"] == "treat"


def test_quantity_escalation_bumps_risk_level(client):
    _setup_hospital(client)
    # SHARPS base risk is HIGH with a 20 threshold — exceeding it should escalate to CRITICAL
    record = _create_classified_record(client, category_code="SHARPS", quantity="25")

    resp = client.post(f"/api/v1/waste/{record['id']}/risk-assessments/run")
    body = resp.json()
    assert body["risk_level"] == "critical"
    assert body["factors"]["quantity_escalated"] is True


def test_general_waste_suggests_dispose(client):
    _setup_hospital(client)
    record = _create_classified_record(client, category_code="GENERAL", quantity="5")

    resp = client.post(f"/api/v1/waste/{record['id']}/risk-assessments/run")
    body = resp.json()
    assert body["risk_level"] == "low"
    assert body["recyclability_decision"] is False
    assert body["suggested_handling"] == "dispose"


def test_confirm_assessment_updates_record_status(client):
    _setup_hospital(client)
    record = _create_classified_record(client, category_code="GENERAL")
    client.post(f"/api/v1/waste/{record['id']}/risk-assessments/run")

    resp = client.post(f"/api/v1/waste/{record['id']}/risk-assessments/confirm")
    assert resp.status_code == 200
    assert resp.json()["is_confirmed"] is True

    detail = client.get(f"/api/v1/waste/{record['id']}").json()
    assert detail["status"] == "risk_assessed"


def test_confirm_without_running_conflicts(client):
    _setup_hospital(client)
    record = _create_classified_record(client, category_code="GENERAL")
    resp = client.post(f"/api/v1/waste/{record['id']}/risk-assessments/confirm")
    assert resp.status_code == 409


def test_confirm_twice_conflicts(client):
    _setup_hospital(client)
    record = _create_classified_record(client, category_code="GENERAL")
    client.post(f"/api/v1/waste/{record['id']}/risk-assessments/run")
    client.post(f"/api/v1/waste/{record['id']}/risk-assessments/confirm")

    resp = client.post(f"/api/v1/waste/{record['id']}/risk-assessments/confirm")
    assert resp.status_code == 409


def test_manual_override_sets_status_and_is_confirmed(client):
    _setup_hospital(client)
    record = _create_classified_record(client, category_code="GENERAL")

    resp = client.post(
        f"/api/v1/waste/{record['id']}/risk-assessments/override",
        json={"risk_level": "medium", "suggested_handling": "dispose", "notes": "Staff judgment call"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "manual"
    assert body["is_confirmed"] is True

    detail = client.get(f"/api/v1/waste/{record['id']}").json()
    assert detail["status"] == "risk_assessed"


def test_risk_assessment_history_newest_first(client):
    _setup_hospital(client)
    record = _create_classified_record(client, category_code="GENERAL")

    client.post(f"/api/v1/waste/{record['id']}/risk-assessments/run")
    client.post(
        f"/api/v1/waste/{record['id']}/risk-assessments/override",
        json={"risk_level": "high", "suggested_handling": "treat"},
    )

    resp = client.get(f"/api/v1/waste/{record['id']}/risk-assessments")
    assert resp.status_code == 200
    history = resp.json()
    assert len(history) == 2
    assert history[0]["source"] == "manual"


def test_risk_assessment_requires_hospital_role(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "driver4@greenhaul.example",
            "password": "CorrectHorseBattery123",
            "full_name": "Driver",
            "role": "collector",
        },
    )
    resp = client.post(
        "/api/v1/waste/00000000-0000-0000-0000-000000000000/risk-assessments/run"
    )
    assert resp.status_code == 403
