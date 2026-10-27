def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "uptime_seconds" in body


def test_health_db(client):
    resp = client.get("/api/v1/health/db")
    assert resp.status_code == 200
    # Reports its own status rather than raising, so a missing DB
    # never turns readiness checks into a hard failure.
    assert resp.json()["status"] in {"ok", "error"}
