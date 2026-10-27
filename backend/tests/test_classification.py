HOSPITAL_USER = {
    "email": "classify-reporter@stalbans.example",
    "password": "CorrectHorseBattery123",
    "full_name": "Classify Reporter",
    "role": "hospital",
}

HOSPITAL_PROFILE = {
    "name": "St. Alban's General Hospital",
    "registration_number": "HRN-48219",
    "contact_person": "Classify Reporter",
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


def _create_record(client, *, category_code="GENERAL", description=None):
    category_id = _category_id(client, category_code)
    payload = {"category_id": category_id, "quantity": "5", "unit": "kg"}
    if description:
        payload["description"] = description
    return client.post("/api/v1/waste", json=payload).json()


def test_classification_agrees_with_reported_category_is_high_confidence(client):
    _setup_hospital(client)
    record = _create_record(
        client, category_code="SHARPS", description="Box of used needles from Ward 4"
    )

    resp = client.post(f"/api/v1/waste/{record['id']}/classifications/run")
    assert resp.status_code == 201
    body = resp.json()
    assert body["suggested_category"]["code"] == "SHARPS"
    assert body["confidence"] == "high"
    assert body["source"] == "rule_engine"
    assert body["is_confirmed"] is False
    assert len(body["matched_rules"]) == 1


def test_classification_conflict_is_medium_confidence(client):
    _setup_hospital(client)
    record = _create_record(
        client, category_code="GENERAL", description="Bag of used needles"
    )

    resp = client.post(f"/api/v1/waste/{record['id']}/classifications/run")
    body = resp.json()
    assert body["suggested_category"]["code"] == "SHARPS"
    assert body["confidence"] == "medium"


def test_classification_with_no_keywords_defaults_low_confidence(client):
    _setup_hospital(client)
    record = _create_record(
        client, category_code="GENERAL", description="Routine ward waste, nothing unusual"
    )

    resp = client.post(f"/api/v1/waste/{record['id']}/classifications/run")
    body = resp.json()
    assert body["suggested_category"]["code"] == "GENERAL"
    assert body["confidence"] == "low"
    assert body["matched_rules"] == []


def test_confirm_classification_updates_record_status_and_category(client):
    _setup_hospital(client)
    record = _create_record(
        client, category_code="GENERAL", description="Used syringes from the ICU"
    )
    client.post(f"/api/v1/waste/{record['id']}/classifications/run")

    resp = client.post(f"/api/v1/waste/{record['id']}/classifications/confirm")
    assert resp.status_code == 200
    assert resp.json()["is_confirmed"] is True

    detail = client.get(f"/api/v1/waste/{record['id']}").json()
    assert detail["status"] == "classified"
    assert detail["category"]["code"] == "SHARPS"


def test_confirm_without_running_classification_conflicts(client):
    _setup_hospital(client)
    record = _create_record(client)
    resp = client.post(f"/api/v1/waste/{record['id']}/classifications/confirm")
    assert resp.status_code == 409


def test_confirm_twice_conflicts(client):
    _setup_hospital(client)
    record = _create_record(client, description="needle")
    client.post(f"/api/v1/waste/{record['id']}/classifications/run")
    client.post(f"/api/v1/waste/{record['id']}/classifications/confirm")

    resp = client.post(f"/api/v1/waste/{record['id']}/classifications/confirm")
    assert resp.status_code == 409


def test_manual_override_sets_category_and_confirms_immediately(client):
    _setup_hospital(client)
    record = _create_record(client, category_code="GENERAL")
    pharma_id = _category_id(client, "PHARMACEUTICAL")

    resp = client.post(
        f"/api/v1/waste/{record['id']}/classifications/override",
        json={"category_id": pharma_id, "notes": "Nurse spotted expired vials on inspection"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "manual"
    assert body["is_confirmed"] is True
    assert body["suggested_category"]["code"] == "PHARMACEUTICAL"

    detail = client.get(f"/api/v1/waste/{record['id']}").json()
    assert detail["status"] == "classified"
    assert detail["category"]["code"] == "PHARMACEUTICAL"


def test_manual_override_unknown_category_rejected(client):
    _setup_hospital(client)
    record = _create_record(client)
    resp = client.post(
        f"/api/v1/waste/{record['id']}/classifications/override",
        json={"category_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 400


def test_classification_history_lists_all_events_newest_first(client):
    _setup_hospital(client)
    record = _create_record(client, description="needle")

    client.post(f"/api/v1/waste/{record['id']}/classifications/run")
    client.post(f"/api/v1/waste/{record['id']}/classifications/run")
    pharma_id = _category_id(client, "PHARMACEUTICAL")
    client.post(
        f"/api/v1/waste/{record['id']}/classifications/override",
        json={"category_id": pharma_id},
    )

    resp = client.get(f"/api/v1/waste/{record['id']}/classifications")
    assert resp.status_code == 200
    history = resp.json()
    assert len(history) == 3
    assert history[0]["source"] == "manual"  # most recent first


def test_classification_requires_hospital_role(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "driver3@greenhaul.example",
            "password": "CorrectHorseBattery123",
            "full_name": "Driver",
            "role": "collector",
        },
    )
    resp = client.post(
        "/api/v1/waste/00000000-0000-0000-0000-000000000000/classifications/run"
    )
    assert resp.status_code == 403


def test_category_free_report_without_description_requires_a_real_manual_category(client):
    _setup_hospital(client)
    response=client.post('/api/v1/waste',json={'quantity':'5','unit':'kg'})
    assert response.status_code==201
    record=response.json()
    proposal=client.post(f"/api/v1/waste/{record['id']}/classifications/run")
    assert proposal.status_code==201 and proposal.json()['suggested_category']['code']=='PENDING'
    assert client.post(f"/api/v1/waste/{record['id']}/classifications/confirm").status_code==409
    category_id=_category_id(client,'GENERAL')
    assert client.post(f"/api/v1/waste/{record['id']}/classifications/override",json={'category_id':category_id}).status_code==200
    assert client.get(f"/api/v1/waste/{record['id']}").json()['status']=='classified'
