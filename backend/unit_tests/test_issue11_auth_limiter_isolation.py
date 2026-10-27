"""Issue 11: rate limits do not leak between independent ASGI applications.

No database, app.main startup, sleep, or external service is required.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.middleware import DemoAuthRateLimitMiddleware


def make_app():
    app = FastAPI()
    app.add_middleware(DemoAuthRateLimitMiddleware)

    @app.post('/api/v1/auth/register')
    def register():
        return {'ok': True}

    @app.post('/api/v1/auth/login')
    def login():
        return {'ok': True}

    @app.get('/api/v1/auth/register')
    def get_registration():
        return {'ok': True}

    @app.post('/api/v1/other')
    def other():
        return {'ok': True}

    return app


def test_registration_burst_is_enforced_per_app():
    with TestClient(make_app()) as client:
        assert all(client.post('/api/v1/auth/register').status_code == 200 for _ in range(10))
        denied = client.post('/api/v1/auth/register')
        assert denied.status_code == 429
        assert denied.headers['retry-after'] == '3600'


def test_separate_app_does_not_inherit_previous_app_attempts():
    with TestClient(make_app()) as first:
        for _ in range(10):
            assert first.post('/api/v1/auth/register').status_code == 200
        assert first.post('/api/v1/auth/register').status_code == 429
    # A new app/middleware instance has independent counters (pytest fixtures).
    with TestClient(make_app()) as second:
        assert second.post('/api/v1/auth/register').status_code == 200


def test_same_app_reuses_counter_between_separate_clients():
    app = make_app()
    with TestClient(app) as first:
        for _ in range(6):
            assert first.post('/api/v1/auth/register').status_code == 200
    with TestClient(app) as second:
        for _ in range(4):
            assert second.post('/api/v1/auth/register').status_code == 200
        assert second.post('/api/v1/auth/register').status_code == 429


def test_login_and_register_counts_are_independent():
    with TestClient(make_app()) as client:
        for _ in range(10):
            assert client.post('/api/v1/auth/register').status_code == 200
        assert client.post('/api/v1/auth/register').status_code == 429
        assert client.post('/api/v1/auth/login').status_code == 200
        for _ in range(19):
            assert client.post('/api/v1/auth/login').status_code == 200
        assert client.post('/api/v1/auth/login').status_code == 429


def test_non_auth_methods_and_paths_are_not_limited():
    with TestClient(make_app()) as client:
        for _ in range(15):
            assert client.get('/api/v1/auth/register').status_code == 200
            assert client.post('/api/v1/other').status_code == 200
        assert client.post('/api/v1/auth/register').status_code == 200


def test_client_supplied_forwarded_ip_is_not_trusted():
    with TestClient(make_app()) as client:
        for i in range(10):
            assert client.post('/api/v1/auth/register', headers={'X-Forwarded-For':f'198.51.100.{i+1}'}).status_code == 200
        assert client.post('/api/v1/auth/register', headers={'X-Forwarded-For':'203.0.113.99'}).status_code == 429


def test_expired_window_reopens(monkeypatch):
    import app.core.middleware as mw
    moment = [10000.0]
    monkeypatch.setattr(mw.time, 'monotonic', lambda: moment[0])
    with TestClient(make_app()) as client:
        for _ in range(10):
            assert client.post('/api/v1/auth/register').status_code == 200
        assert client.post('/api/v1/auth/register').status_code == 429
        moment[0] += 3601
        assert client.post('/api/v1/auth/register').status_code == 200
