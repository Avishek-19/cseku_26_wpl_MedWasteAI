"""WebSocket access revalidation and idle database-connection regression tests."""
import time
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect
from app import models  # noqa: F401
from app.core.db import Base
from app.models.user import User
from app.models.roles import UserRole
from app.api import tracking_ws
from app.realtime.tracking_manager import TrackingConnectionManager


@pytest.fixture
def socket_context(tmp_path, monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'sockets.db'),connect_args={'check_same_thread':False},pool_size=1,max_overflow=0,pool_timeout=.3)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user=User(email='socket@example.org',full_name='Driver',hashed_password='not used',role=UserRole.COLLECTOR,is_active=True)
        db.add(user);db.commit();identifier=user.id
    config=SimpleNamespace(auth_cookie_name='mw_session',cors_origin_list=['http://localhost'],websocket_enabled=True,websocket_heartbeat_seconds=.05)
    claims={'sub':str(identifier),'ver':0,'exp':time.time()+30}
    monkeypatch.setattr(tracking_ws,'get_settings',lambda:config)
    monkeypatch.setattr(tracking_ws,'SessionLocal',lambda **kwargs:Session(engine,**kwargs))
    monkeypatch.setattr(tracking_ws,'decode_access_token',lambda token:claims)
    monkeypatch.setattr(tracking_ws,'tracking_manager',TrackingConnectionManager())
    app=FastAPI();app.include_router(tracking_ws.router)
    with TestClient(app,base_url='http://localhost') as client:
        client.cookies.set('mw_session','validated-by-fixture')
        yield client,engine,identifier,claims
    engine.dispose()


def next_event(ws, expected):
    for _ in range(20):
        event=ws.receive_json()
        if event.get('type')=='ping':ws.send_json({'type':'pong'});continue
        assert event['type']==expected,event
        return event
    raise AssertionError('Expected event did not arrive')


def test_idle_socket_does_not_exhaust_single_connection_pool(socket_context):
    client,engine,user,claims=socket_context
    with client.websocket_connect('/api/v1/tracking/ws') as ws:
        next_event(ws,'connected')
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT 1'))==1
        ws.send_json([])
        assert next_event(ws,'error')['code']=='INVALID_EVENT'


def test_open_socket_closes_after_password_session_version_changes(socket_context):
    client,engine,identifier,claims=socket_context
    with client.websocket_connect('/api/v1/tracking/ws') as ws:
        next_event(ws,'connected')
        with Session(engine) as db:
            db.get(User,identifier).auth_version=1;db.commit()
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:ws.receive_json()
        assert closed.value.code==1008


def test_open_socket_closes_when_original_token_expires(socket_context):
    client,engine,user,claims=socket_context
    claims['exp']=time.time()+.15
    with client.websocket_connect('/api/v1/tracking/ws') as ws:
        next_event(ws,'connected')
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:ws.receive_json()
        assert closed.value.code==1008
