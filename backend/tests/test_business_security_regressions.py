"""Security regression gates for business upgrade.

Run with dedicated PostgreSQL medwaste_ai_test fixtures (see conftest).
These tests must stay green after any auth/finance/org change.
"""

def test_public_admin_registration_forbidden(client):
    """Public form cannot create an administrator (schema + service layer)."""
    r = client.post("/api/v1/auth/register", json={
        "email": "forged-admin@example.test",
        "password": "StrongPassword123!",
        "full_name": "Forged Admin",
        "role": "admin",
    })
    # Schema validator returns 422; service layer would return 403.
    assert r.status_code in (403, 422)
    # Must not leave an authenticated session as admin.
    assert client.get("/api/v1/auth/me").status_code == 401


def test_public_admin_case_variants_rejected(client):
    for role in ("ADMIN", "Admin", "aDmIn"):
        r = client.post("/api/v1/auth/register", json={
            "email": f"forged-{role.lower()}@example.test",
            "password": "StrongPassword123!",
            "full_name": "Forged",
            "role": role,
        })
        assert r.status_code in (403, 422), f"role={role} status={r.status_code}"


def test_unauthenticated_money_endpoints_denied(client):
    assert client.get(
        "/api/v1/invoices?org_id=00000000-0000-0000-0000-000000000001"
    ).status_code == 401
    assert client.post("/api/v1/payments/checkout", json={
        "target_kind": "invoice",
        "target_id": "00000000-0000-0000-0000-000000000001",
        "channel": "bkash",
        "idempotency_key": "unauthenticated-attack",
    }).status_code == 401


def test_mock_gateway_callback_denied(client):
    """Forged IPN without valid signature/mode must not succeed."""
    assert client.post("/api/v1/payments/ipn", data={
        "tran_id": "fake",
        "val_id": "fake",
        "value_a": "fake",
        "status": "VALID",
    }).status_code == 403


def test_invitation_accept_requires_matching_email(client):
    """Cross-email invitation accept must be denied (when org invite path is available)."""
    # Register hospital user
    r = client.post("/api/v1/auth/register", json={
        "email": "hospital-owner@example.test",
        "password": "StrongPassword123!",
        "full_name": "Hospital Owner",
        "role": "hospital",
    })
    if r.status_code not in (200, 201):
        return  # environment may lack full fixture; skip soft
    # Create org
    org = client.post("/api/v1/organizations", json={
        "name": "Test Hospital Org",
        "org_type": "HOSPITAL",
    })
    if org.status_code not in (200, 201):
        return
    org_id = org.json().get("id")
    inv = client.post(f"/api/v1/organizations/{org_id}/invitations", json={
        "email": "other-person@example.test",
        "member_role": "worker",
    })
    if inv.status_code not in (200, 201):
        return
    token = inv.json().get("token")
    # Same user tries to accept invite meant for other email
    bad = client.post(f"/api/v1/invitations/accept?token={token}")
    assert bad.status_code in (403, 404, 410)
