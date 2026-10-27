HOSPITAL_USER = {
    "email": "intake@stalbans.example",
    "password": "CorrectHorseBattery123",
    "full_name": "Intake Coordinator",
    "role": "hospital",
}

COLLECTOR_USER = {
    "email": "driver@greenhaul.example",
    "password": "CorrectHorseBattery123",
    "full_name": "Route Driver",
    "role": "collector",
}

PROFILE_PAYLOAD = {
    "name": "St. Alban's General Hospital",
    "registration_number": "HRN-48219",
    "contact_person": "Intake Coordinator",
    "phone": "+1-555-0134",
    "address_line": "400 Alban Way",
    "city": "Rivermill",
    "region": "Rivermill County",
    "postal_code": "48210",
    "bed_count": 220,
}


def _register(client, user=HOSPITAL_USER):
    return client.post("/api/v1/auth/register", json=user)


def test_get_profile_before_creation_returns_null(client):
    _register(client)
    resp = client.get("/api/v1/hospitals/me")
    assert resp.status_code == 200
    assert resp.json() is None


def test_create_and_fetch_profile(client):
    _register(client)
    resp = client.post("/api/v1/hospitals/me", json=PROFILE_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == PROFILE_PAYLOAD["name"]
    assert body["is_verified"] is False

    resp = client.get("/api/v1/hospitals/me")
    assert resp.status_code == 200
    assert resp.json()["registration_number"] == "HRN-48219"


def test_create_profile_twice_conflicts(client):
    _register(client)
    client.post("/api/v1/hospitals/me", json=PROFILE_PAYLOAD)
    resp = client.post("/api/v1/hospitals/me", json=PROFILE_PAYLOAD)
    assert resp.status_code == 409


def test_update_profile(client):
    _register(client)
    client.post("/api/v1/hospitals/me", json=PROFILE_PAYLOAD)

    updated = {**PROFILE_PAYLOAD, "bed_count": 260, "contact_person": "New Coordinator"}
    resp = client.put("/api/v1/hospitals/me", json=updated)
    assert resp.status_code == 200
    assert resp.json()["bed_count"] == 260
    assert resp.json()["contact_person"] == "New Coordinator"


def test_update_profile_before_creation_404s(client):
    _register(client)
    resp = client.put("/api/v1/hospitals/me", json=PROFILE_PAYLOAD)
    assert resp.status_code == 404


def test_non_hospital_role_forbidden(client):
    _register(client, COLLECTOR_USER)
    resp = client.get("/api/v1/hospitals/me")
    assert resp.status_code == 403


def test_dashboard_stats_reflect_profile_state(client):
    _register(client)

    resp = client.get("/api/v1/hospitals/me/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile_complete"] is False
    assert body["is_verified"] is False
    assert body["total_waste_records"] == 0
    assert body["waste_tracking_available"] is False

    client.post("/api/v1/hospitals/me", json=PROFILE_PAYLOAD)
    resp = client.get("/api/v1/hospitals/me/stats")
    assert resp.json()["profile_complete"] is True


def test_update_account_name(client):
    _register(client)
    resp = client.patch("/api/v1/auth/me", json={"full_name": "Updated Name"})
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Updated Name"


def test_change_password_flow(client):
    _register(client)

    resp = client.post(
        "/api/v1/auth/me/change-password",
        json={"current_password": "wrong-password", "new_password": "BrandNewPW123"},
    )
    assert resp.status_code == 401

    resp = client.post(
        "/api/v1/auth/me/change-password",
        json={
            "current_password": HOSPITAL_USER["password"],
            "new_password": "BrandNewPW123",
        },
    )
    assert resp.status_code == 204

    client.cookies.clear()
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": HOSPITAL_USER["email"], "password": "BrandNewPW123"},
    )
    assert resp.status_code == 200
