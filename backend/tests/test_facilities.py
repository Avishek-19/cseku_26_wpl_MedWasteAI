FACILITY_USER = {
    "email": "intake@cleanburn.example",
    "password": "CorrectHorseBattery123",
    "full_name": "Facility Manager",
    "role": "facility",
}
HOSPITAL_USER = {
    "email": "not-a-facility@stalbans.example",
    "password": "CorrectHorseBattery123",
    "full_name": "Hospital User",
    "role": "hospital",
}
FACILITY_PROFILE = {
    "name": "CleanBurn Treatment Facility",
    "registration_number": "TRT-2201",
    "contact_person": "Facility Manager",
    "phone": "+1-555-0199",
    "address_line": "88 Industrial Row",
    "city": "Rivermill",
    "region": "Rivermill County",
    "postal_code": "48230",
    "capacity_kg": "5000",
}


def _register(client):
    client.post("/api/v1/auth/register", json=FACILITY_USER)


def _category_ids(client, codes):
    """Looks up category IDs via a throwaway hospital account, then leaves
    the facility user logged in (registering it if this is the first call)."""
    client.cookies.clear()
    client.post(
        "/api/v1/auth/register",
        json={**HOSPITAL_USER, "email": f"lookup-{'-'.join(codes).lower()}@stalbans.example"},
    )
    categories = client.get("/api/v1/waste/categories").json()
    ids = {c["code"]: c["id"] for c in categories if c["code"] in codes}

    client.cookies.clear()
    resp = client.post("/api/v1/auth/register", json=FACILITY_USER)
    if resp.status_code != 201:
        client.post(
            "/api/v1/auth/login",
            json={"email": FACILITY_USER["email"], "password": FACILITY_USER["password"]},
        )
    return ids


def test_get_profile_before_creation_returns_null(client):
    _register(client)
    resp = client.get("/api/v1/facilities/me")
    assert resp.status_code == 200
    assert resp.json() is None


def test_create_and_fetch_profile(client):
    _register(client)
    resp = client.post("/api/v1/facilities/me", json=FACILITY_PROFILE)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == FACILITY_PROFILE["name"]
    assert body["is_verified"] is False
    assert body["current_utilization_kg"] == "0.00"

    resp = client.get("/api/v1/facilities/me")
    assert resp.json()["registration_number"] == "TRT-2201"


def test_create_profile_twice_conflicts(client):
    _register(client)
    client.post("/api/v1/facilities/me", json=FACILITY_PROFILE)
    resp = client.post("/api/v1/facilities/me", json=FACILITY_PROFILE)
    assert resp.status_code == 409


def test_update_profile(client):
    _register(client)
    client.post("/api/v1/facilities/me", json=FACILITY_PROFILE)
    updated = {**FACILITY_PROFILE, "capacity_kg": "8000"}
    resp = client.put("/api/v1/facilities/me", json=updated)
    assert resp.status_code == 200
    assert resp.json()["capacity_kg"] == "8000.00"


def test_non_facility_role_forbidden(client):
    client.post("/api/v1/auth/register", json=HOSPITAL_USER)
    resp = client.get("/api/v1/facilities/me")
    assert resp.status_code == 403


def test_accepted_categories_requires_profile_first(client):
    _register(client)
    resp = client.get("/api/v1/facilities/me/accepted-categories")
    assert resp.status_code == 404


def test_set_and_get_accepted_categories(client):
    ids = _category_ids(client, ["INFECTIOUS", "SHARPS"])
    client.post("/api/v1/facilities/me", json=FACILITY_PROFILE)

    resp = client.put(
        "/api/v1/facilities/me/accepted-categories",
        json={"category_ids": [ids["INFECTIOUS"], ids["SHARPS"]]},
    )
    assert resp.status_code == 200
    codes = {c["code"] for c in resp.json()}
    assert codes == {"INFECTIOUS", "SHARPS"}

    resp = client.get("/api/v1/facilities/me/accepted-categories")
    assert len(resp.json()) == 2


def test_set_accepted_categories_unknown_category_rejected(client):
    _register(client)
    client.post("/api/v1/facilities/me", json=FACILITY_PROFILE)
    resp = client.put(
        "/api/v1/facilities/me/accepted-categories",
        json={"category_ids": ["00000000-0000-0000-0000-000000000000"]},
    )
    assert resp.status_code == 400


def test_dashboard_stats_reflect_profile_and_categories(client):
    _register(client)
    resp = client.get("/api/v1/facilities/me/stats")
    assert resp.json()["profile_complete"] is False

    client.post("/api/v1/facilities/me", json=FACILITY_PROFILE)
    resp = client.get("/api/v1/facilities/me/stats")
    body = resp.json()
    assert body["profile_complete"] is True
    assert body["capacity_kg"] == "5000.00"
    assert body["utilization_percent"] == 0.0
    assert body["accepted_category_count"] == 0
    assert body["matching_available"] is False
