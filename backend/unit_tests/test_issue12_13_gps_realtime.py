"""Issue 12/13 regression tests: signed/replay-safe GPS + process fan-out."""
import asyncio
import hashlib
import hmac
import json
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.core.config import Settings
from app.core.db import Base
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.roles import UserRole
from app.models.tracking import GPSDeviceNonce, LocationSource, TrackingSession, TrackingSessionStatus
from app.models.route import Route, RouteStatus, RouteStop, RouteStopStatus
from app.models.waste_enums import VehicleStatus
from app.models.pickup_request import PickupRequest
from app.models.hospital_profile import HospitalProfile
from app.models.waste_enums import PickupStatus, PickupPriority
from app.realtime.tracking_manager import TrackingConnectionManager, vehicle_topic
from app.schemas.tracking import GPSLocationCreate
from app.services.gps_device_provenance import (GPSProvenanceError, canonical_message,
    verify_gps_signature)
from app.services.gps_validation_service import GPSValidationError
from app.services.tracking_service import TrackingService


def setup_route():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    db = Session(engine)
    collector = User(email='gpscollector@example.test', full_name='Driver', hashed_password='x', role=UserRole.COLLECTOR)
    hospital_user = User(email='gpsh@example.test', full_name='Hospital', hashed_password='x', role=UserRole.HOSPITAL)
    db.add_all([collector, hospital_user]); db.flush()
    hospital = HospitalProfile(user_id=hospital_user.id, name='Hospital',registration_number='R10',
        contact_person='H', phone='123', address_line='Road', city='Khulna',region='Khulna',postal_code='9000')
    db.add(hospital);db.flush()
    vehicle = Vehicle(vehicle_code='GPS-1',assigned_collector_id=collector.id,capacity_kg=Decimal('300'),
        status=VehicleStatus.ON_ROUTE,is_active=True)
    db.add(vehicle);db.flush()
    pickup = PickupRequest(hospital_id=hospital.id, requested_by=hospital_user.id,
        priority=PickupPriority.NORMAL,status=PickupStatus.ASSIGNED,
        assigned_collector_id=collector.id, assigned_vehicle_id=vehicle.id)
    db.add(pickup);db.flush()
    route = Route(vehicle_id=vehicle.id,status=RouteStatus.ACTIVE,version=1,destination_state='collection',
        origin_latitude=Decimal('22.81'),origin_longitude=Decimal('89.55'))
    db.add(route);db.flush()
    stop = RouteStop(route_id=route.id,pickup_id=pickup.id,sequence=1,latitude=Decimal('22.81'),
        longitude=Decimal('89.55'),status=RouteStopStatus.EN_ROUTE)
    session = TrackingSession(vehicle_id=vehicle.id,current_route_id=route.id,
        status=TrackingSessionStatus.ACTIVE,started_at=datetime.now(timezone.utc))
    db.add_all([stop,session]);db.commit()
    return engine,db,collector,vehicle,session,stop


def signed(settings, session, vehicle, data, key, device_id, nonce=None, timestamp=None):
    nonce = nonce or uuid.uuid4()
    issued = int(datetime.now(timezone.utc).timestamp()) if timestamp is None else timestamp
    signature = hmac.new(key,canonical_message(session.id,device_id,nonce,issued,data),hashlib.sha256).hexdigest()
    return verify_gps_signature(settings,session_id=session.id,vehicle_id=vehicle.id,
        payload=data,device_id=str(device_id),nonce=str(nonce),sent_at=str(issued),signature=signature,
        now=int(datetime.now(timezone.utc).timestamp()))


def test_untrusted_source_cannot_advance_geofence_even_with_plausible_location():
    engine,db,user,vehicle,session,stop=setup_route()
    try:
        settings=Settings(database_url='sqlite+pysqlite:///:memory:')
        data=GPSLocationCreate(latitude=22.81,longitude=89.55,
            timestamp=datetime.now(timezone.utc),accuracy_m=5,source=LocationSource.GPS_DEVICE)
        location=TrackingService(db,settings).record_location(user=user,session_id=session.id,data=data)
        assert location.source == LocationSource.GPS_DEVICE
        assert location.provenance_verified is False
        assert db.get(RouteStop, stop.id).status == RouteStopStatus.EN_ROUTE
    finally:db.close();engine.dispose()


def test_registered_gps_signature_can_advance_and_prevent_replay():
    engine,db,user,vehicle,session,stop=setup_route()
    try:
        key=bytes.fromhex('ab'*32);device_id=uuid.uuid4()
        settings=Settings(database_url='sqlite+pysqlite:///:memory:', gps_trusted_devices_json=json.dumps({
            str(device_id):{'vehicle_id':str(vehicle.id),'secret_hex':key.hex()}}))
        data=GPSLocationCreate(latitude=22.81,longitude=89.55,
            timestamp=datetime.now(timezone.utc),accuracy_m=5,source=LocationSource.GPS_DEVICE)
        verified=signed(settings,session,vehicle,data,key,device_id)
        loc=TrackingService(db,settings).record_location(user=user,session_id=session.id,
            data=data,verified_device=verified)
        assert loc.provenance_verified is True
        assert db.get(RouteStop,stop.id).status == RouteStopStatus.ARRIVED
        assert db.scalar(select(GPSDeviceNonce).where(GPSDeviceNonce.nonce==verified.nonce)) is not None
        with pytest.raises(GPSValidationError,match='Repeated GPS device nonce'):
            TrackingService(db,settings).record_location(user=user,session_id=session.id,
                data=data,verified_device=verified)
    finally:db.close();engine.dispose()


def test_gps_device_signature_wrong_vehicle_tampering_and_stale_rejected():
    engine,db,user,vehicle,session,stop=setup_route()
    try:
        key=bytes.fromhex('ce'*32); did=uuid.uuid4()
        settings=Settings(database_url='sqlite+pysqlite:///:memory:',gps_trusted_devices_json=json.dumps({
            str(did):{'vehicle_id':str(vehicle.id),'secret_hex':key.hex()}}))
        data=GPSLocationCreate(latitude=22.81,longitude=89.55,
            timestamp=datetime.now(timezone.utc),accuracy_m=4,source=LocationSource.MOBILE_APP)
        evidence=signed(settings,session,vehicle,data,key,did)
        assert evidence.device_id==did
        wrong=uuid.uuid4()
        with pytest.raises(GPSProvenanceError):
            signed(settings,session,type('Other',(),{'id':wrong})(),data,key,did)
        with pytest.raises(GPSProvenanceError):
            signed(settings,session,vehicle,data.model_copy(update={'latitude':Decimal('22.82')}),b'Z'*32,did)
        with pytest.raises(GPSProvenanceError):
            signed(settings,session,vehicle,data,key,did,timestamp=int(datetime.now(timezone.utc).timestamp())-120)
        with pytest.raises(GPSProvenanceError):
            signed(settings,session,vehicle,data.model_copy(update={'source':LocationSource.SIMULATOR}),key,did)
    finally:db.close();engine.dispose()


def test_multiworker_requires_shared_transport():
    with pytest.raises(ValueError,match='TRACKING_REDIS_URL'):
        Settings(tracking_worker_count=2)
    assert Settings(tracking_worker_count=2,tracking_redis_url='redis://localhost:6379/0').tracking_worker_count==2


class FakeSocket:
    def __init__(self):self.messages=[]
    async def accept(self):pass
    async def send_json(self,event):self.messages.append(event)


class Broker:
    def __init__(self):self.subscribers=set()
    async def publish(self,channel,message):
        for subscription in list(self.subscribers):
            if subscription.channel==channel:await subscription.queue.put({'type':'message','data':message})


class FakePubSub:
    def __init__(self,broker):self.broker=broker;self.queue=asyncio.Queue();self.channel=None
    async def __aenter__(self):return self
    async def __aexit__(self,*args):self.broker.subscribers.discard(self)
    async def subscribe(self,channel):self.channel=channel;self.broker.subscribers.add(self)
    async def listen(self):
        while True:yield await self.queue.get()


class FakeRedis:
    broker=Broker()
    @classmethod
    def from_url(cls,url,**kwargs):return cls()
    async def ping(self):return True
    def pubsub(self,**kwargs):return FakePubSub(self.broker)
    async def publish(self,channel,message):await self.broker.publish(channel,message)
    async def aclose(self):pass


def test_redis_fanout_delivers_once_across_workers_and_filters_topics(monkeypatch):
    async def run():
        FakeRedis.broker=Broker()
        fake_parent=types.ModuleType('redis');fake_parent.__path__=[]
        fake_async=types.ModuleType('redis.asyncio');fake_async.Redis=FakeRedis
        monkeypatch.setitem(sys.modules,'redis',fake_parent)
        monkeypatch.setitem(sys.modules,'redis.asyncio',fake_async)
        first,second=TrackingConnectionManager(),TrackingConnectionManager()
        await first.start(redis_url='redis://fake')
        await second.start(redis_url='redis://fake')
        one,two=FakeSocket(),FakeSocket()
        await first.connect(one);await second.connect(two)
        await first.subscribe(one,{'vehicle:v1'})
        await second.subscribe(two,{'vehicle:v1'})
        await first.broadcast({'type':'location_update','n':1},{'vehicle:v1'})
        await asyncio.sleep(0.02)
        assert one.messages==[{'type':'location_update','n':1}]
        assert two.messages==[{'type':'location_update','n':1}]
        await second.unsubscribe(two,{'vehicle:v1'})
        await first.broadcast({'type':'location_update','n':2},{'vehicle:v1'})
        await asyncio.sleep(0.02)
        assert len(one.messages)==2 and len(two.messages)==1
        await first.broadcast({'type':'unrelated'},{'route:other'})
        await asyncio.sleep(0.02)
        assert len(one.messages)==2 and len(two.messages)==1
        await first.stop();await second.stop()
    asyncio.run(run())


def test_single_worker_without_broker_keeps_local_broadcast():
    async def run():
        mgr=TrackingConnectionManager()
        await mgr.start()
        ws=FakeSocket()
        await mgr.connect(ws)
        await mgr.subscribe(ws,{'vehicle:one'})
        await mgr.broadcast({'type':'ping'},{'vehicle:one'})
        assert ws.messages==[{'type':'ping'}]
        await mgr.stop()
    asyncio.run(run())


def test_real_location_api_requires_complete_signed_headers_and_flags_unsigned(monkeypatch):
    from starlette.requests import Request
    from fastapi import HTTPException
    # The isolated test image lacks the bcrypt package. No auth hashing is
    # exercised here; use a throwaway import shim only in this test function.
    try:
        import bcrypt  # noqa: F401
    except ImportError:
        shim = types.ModuleType('bcrypt')
        monkeypatch.setitem(sys.modules, 'bcrypt', shim)
    import app.api.tracking as api

    engine,db,user,vehicle,session,stop=setup_route()
    try:
        key=bytes.fromhex('91'*32);device_id=uuid.uuid4();nonce=uuid.uuid4()
        settings=Settings(database_url='sqlite+pysqlite:///:memory:',gps_trusted_devices_json=json.dumps({
            str(device_id):{'vehicle_id':str(vehicle.id),'secret_hex':key.hex()}}))
        monkeypatch.setattr(api,'get_settings',lambda:settings)
        data=GPSLocationCreate(latitude=22.81,longitude=89.55,
            timestamp=datetime.now(timezone.utc),accuracy_m=4,source=LocationSource.GPS_DEVICE)
        def request(headers=None):
            headers=headers or {}
            return Request({'type':'http','method':'POST','scheme':'http','path':'/gps',
                'query_string':b'','headers':[(k.lower().encode(),v.encode()) for k,v in headers.items()]})
        async def run():
            with pytest.raises(HTTPException) as e:
                await api.record_location(session_id=session.id,payload=data,
                    request=request({'x-gps-device-id':str(device_id)}),current_user=user,db=db)
            assert e.value.status_code==403
            unsigned=await api.record_location(session_id=session.id,payload=data,
                request=request(),current_user=user,db=db)
            assert unsigned.provenance_verified is False
            assert db.get(RouteStop,stop.id).status==RouteStopStatus.EN_ROUTE
            # Signed report must carry a unique, tamper-proof session/device
            # binding. A newer source timestamp avoids treating it as stale.
            fresh=data.model_copy(update={'timestamp':datetime.now(timezone.utc)+timedelta(seconds=2)})
            sent_at=int(datetime.now(timezone.utc).timestamp())
            signature=hmac.new(key,canonical_message(session.id,device_id,nonce,sent_at,fresh),hashlib.sha256).hexdigest()
            signed_location=await api.record_location(session_id=session.id,payload=fresh,
                request=request({'x-gps-device-id':str(device_id),'x-gps-nonce':str(nonce),
                    'x-gps-sent-at':str(sent_at),'x-gps-signature':signature}),current_user=user,db=db)
            assert signed_location.provenance_verified is True
            assert db.get(RouteStop,stop.id).status==RouteStopStatus.ARRIVED
        asyncio.run(run())
    finally:db.close();engine.dispose()


def test_sync_publisher_without_local_websocket_reaches_second_worker(monkeypatch):
    async def run():
        FakeRedis.broker=Broker()
        parent=types.ModuleType('redis');parent.__path__=[]
        fake_async=types.ModuleType('redis.asyncio');fake_async.Redis=FakeRedis
        monkeypatch.setitem(sys.modules,'redis',parent)
        monkeypatch.setitem(sys.modules,'redis.asyncio',fake_async)
        publisher,subscriber=TrackingConnectionManager(),TrackingConnectionManager()
        await publisher.start(redis_url='redis://fake')
        await subscriber.start(redis_url='redis://fake')
        ws=FakeSocket()
        await subscriber.connect(ws)
        await subscriber.subscribe(ws,{'route:abc'})
        # A sync FastAPI API endpoint runs in a thread; the publishing worker
        # intentionally has no websocket and must still publish to Redis.
        await asyncio.to_thread(publisher.broadcast_from_sync, {'type':'route_update'}, {'route:abc'})
        await asyncio.sleep(0.025)
        assert ws.messages==[{'type':'route_update'}]
        await subscriber.stop();await publisher.stop()
    asyncio.run(run())
