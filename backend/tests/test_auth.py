import pytest

from app.api.deps import require_roles
from app.models.roles import UserRole

VALID_USER = {
    "email": "ward.nurse@stalbans.example",
    "password": "CorrectHorseBattery123",
    "full_name": "Ward Nurse",
    "role": "hospital",
}


def test_register_creates_user_and_sets_session(client):
    resp = client.post("/api/v1/auth/register", json=VALID_USER)
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == VALID_USER["email"]
    assert body["role"] == "hospital"
    assert "hashed_password" not in body
    assert client.cookies.get("mw_session") is not None


def test_register_duplicate_email_rejected(client):
    client.post("/api/v1/auth/register", json=VALID_USER)
    resp = client.post("/api/v1/auth/register", json=VALID_USER)
    assert resp.status_code == 409


def test_register_short_password_rejected(client):
    bad = {**VALID_USER, "password": "short"}
    resp = client.post("/api/v1/auth/register", json=bad)
    assert resp.status_code == 422


def test_login_with_correct_credentials(client):
    client.post("/api/v1/auth/register", json=VALID_USER)
    client.cookies.clear()

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == VALID_USER["email"]


def test_login_with_wrong_password_rejected(client):
    client.post("/api/v1/auth/register", json=VALID_USER)
    client.cookies.clear()

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": VALID_USER["email"], "password": "wrong-password"},
    )
    assert resp.status_code == 401


def test_me_requires_authentication(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_returns_current_user_after_login(client):
    client.post("/api/v1/auth/register", json=VALID_USER)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["full_name"] == VALID_USER["full_name"]


def test_logout_clears_session(client):
    client.post("/api/v1/auth/register", json=VALID_USER)
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 204

    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_role_based_access_control_dependency():
    """Unit-level check that require_roles rejects users outside the allow-list."""
    from fastapi import HTTPException

    class FakeUser:
        role = UserRole.HOSPITAL

    checker = require_roles(UserRole.ADMIN)

    with pytest.raises(HTTPException) as exc_info:
        checker(user=FakeUser())
    assert exc_info.value.status_code == 403
