import io

HOSPITAL_USER = {
    "email": "waste-reporter@stalbans.example",
    "password": "CorrectHorseBattery123",
    "full_name": "Waste Reporter",
    "role": "hospital",
}

COLLECTOR_USER = {
    "email": "driver2@greenhaul.example",
    "password": "CorrectHorseBattery123",
    "full_name": "Route Driver",
    "role": "collector",
}

HOSPITAL_PROFILE = {
    "name": "St. Alban's General Hospital",
    "registration_number": "HRN-48219",
    "contact_person": "Waste Reporter",
    "phone": "+1-555-0134",
    "address_line": "400 Alban Way",
    "city": "Rivermill",
    "region": "Rivermill County",
    "postal_code": "48210",
    "bed_count": 220,
}


def _register_hospital_with_profile(client):
    client.post("/api/v1/auth/register", json=HOSPITAL_USER)
    client.post("/api/v1/hospitals/me", json=HOSPITAL_PROFILE)


def _get_category_id(client, code="GENERAL"):
    categories = client.get("/api/v1/waste/categories").json()
    return next(c["id"] for c in categories if c["code"] == code)


def test_list_categories_returns_seeded_categories(client):
    _register_hospital_with_profile(client)
    resp = client.get("/api/v1/waste/categories")
    assert resp.status_code == 200
    codes = {c["code"] for c in resp.json()}
    assert {"GENERAL", "INFECTIOUS", "SHARPS", "RECYCLABLE"}.issubset(codes)


def test_create_waste_record_requires_hospital_profile(client):
    client.post("/api/v1/auth/register", json=HOSPITAL_USER)
    category_id = client.get("/api/v1/waste/categories").json()[0]["id"]
    resp = client.post(
        "/api/v1/waste",
        json={"category_id": category_id, "quantity": "12.5", "unit": "kg"},
    )
    assert resp.status_code == 412


def test_create_waste_record_generates_waste_code(client):
    _register_hospital_with_profile(client)
    category_id = _get_category_id(client)

    resp = client.post(
        "/api/v1/waste",
        json={
            "category_id": category_id,
            "quantity": "12.5",
            "unit": "kg",
            "description": "Ward 4 sharps bin",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["waste_code"].startswith("MW-")
    assert body["status"] == "reported"
    assert body["category"]["code"] == "GENERAL"


def test_create_waste_record_unknown_category_rejected(client):
    _register_hospital_with_profile(client)
    resp = client.post(
        "/api/v1/waste",
        json={
            "category_id": "00000000-0000-0000-0000-000000000000",
            "quantity": "1",
            "unit": "kg",
        },
    )
    assert resp.status_code == 400


def test_create_waste_record_rejects_non_positive_quantity(client):
    _register_hospital_with_profile(client)
    category_id = _get_category_id(client)
    resp = client.post(
        "/api/v1/waste", json={"category_id": category_id, "quantity": "0", "unit": "kg"}
    )
    assert resp.status_code == 422


def test_non_hospital_role_forbidden(client):
    client.post("/api/v1/auth/register", json=COLLECTOR_USER)
    resp = client.get("/api/v1/waste/categories")
    assert resp.status_code == 403


def test_get_waste_record_detail(client):
    _register_hospital_with_profile(client)
    category_id = _get_category_id(client)
    created = client.post(
        "/api/v1/waste", json={"category_id": category_id, "quantity": "5", "unit": "kg"}
    ).json()

    resp = client.get(f"/api/v1/waste/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["waste_code"] == created["waste_code"]


def test_get_waste_record_not_found(client):
    _register_hospital_with_profile(client)
    resp = client.get("/api/v1/waste/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_list_waste_records_pagination_and_search(client):
    _register_hospital_with_profile(client)
    category_id = _get_category_id(client)

    for i in range(5):
        client.post(
            "/api/v1/waste",
            json={
                "category_id": category_id,
                "quantity": str(i + 1),
                "unit": "kg",
                "description": f"Batch {i}",
            },
        )

    resp = client.get("/api/v1/waste", params={"page": 1, "page_size": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["total_pages"] == 3

    resp = client.get("/api/v1/waste", params={"search": "Batch 3"})
    assert resp.json()["total"] == 1


def test_list_waste_records_filters_by_status_and_category(client):
    _register_hospital_with_profile(client)
    general_id = _get_category_id(client, "GENERAL")
    sharps_id = _get_category_id(client, "SHARPS")

    client.post("/api/v1/waste", json={"category_id": general_id, "quantity": "1", "unit": "kg"})
    client.post("/api/v1/waste", json={"category_id": sharps_id, "quantity": "1", "unit": "kg"})

    resp = client.get("/api/v1/waste", params={"category_id": sharps_id})
    assert resp.json()["total"] == 1

    resp = client.get("/api/v1/waste", params={"status": "reported"})
    assert resp.json()["total"] == 2

    resp = client.get("/api/v1/waste", params={"status": "collected"})
    assert resp.json()["total"] == 0


def test_upload_attachment_and_download(client):
    _register_hospital_with_profile(client)
    category_id = _get_category_id(client)
    record = client.post(
        "/api/v1/waste", json={"category_id": category_id, "quantity": "1", "unit": "kg"}
    ).json()

    file_bytes = b"\x89PNG\r\n\x1a\nfake-png-bytes"
    resp = client.post(
        f"/api/v1/waste/{record['id']}/attachments",
        files={"file": ("bin.png", io.BytesIO(file_bytes), "image/png")},
    )
    assert resp.status_code == 201
    attachment = resp.json()
    assert attachment["original_filename"] == "bin.png"
    assert attachment["size_bytes"] == len(file_bytes)

    resp = client.get(
        f"/api/v1/waste/{record['id']}/attachments/{attachment['id']}/download"
    )
    assert resp.status_code == 200
    assert resp.content == file_bytes

    detail = client.get(f"/api/v1/waste/{record['id']}").json()
    assert len(detail["attachments"]) == 1


def test_upload_attachment_rejects_disallowed_type(client):
    _register_hospital_with_profile(client)
    category_id = _get_category_id(client)
    record = client.post(
        "/api/v1/waste", json={"category_id": category_id, "quantity": "1", "unit": "kg"}
    ).json()

    resp = client.post(
        f"/api/v1/waste/{record['id']}/attachments",
        files={"file": ("script.exe", io.BytesIO(b"MZ..."), "application/x-msdownload")},
    )
    assert resp.status_code == 400


def test_attachment_for_other_hospitals_record_is_not_found(client):
    _register_hospital_with_profile(client)
    category_id = _get_category_id(client)
    record = client.post(
        "/api/v1/waste", json={"category_id": category_id, "quantity": "1", "unit": "kg"}
    ).json()
    client.post(
        f"/api/v1/waste/{record['id']}/attachments",
        files={"file": ("bin.png", io.BytesIO(b"data"), "image/png")},
    )

    # A second hospital account should not be able to see the first one's record.
    client.cookies.clear()
    other_hospital = {**HOSPITAL_USER, "email": "other-hospital@example.com"}
    client.post("/api/v1/auth/register", json=other_hospital)
    client.post("/api/v1/hospitals/me", json=HOSPITAL_PROFILE)

    resp = client.get(f"/api/v1/waste/{record['id']}")
    assert resp.status_code == 404
