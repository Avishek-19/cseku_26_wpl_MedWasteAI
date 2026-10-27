"""GPS provenance proof: server-enrolled HMAC key, session and vehicle binding.

This authenticates the *sender* and protects message integrity; it does not
attest that the device's physical sensors have not been manipulated. Do not
advertise HMAC verification as OS-level hardware attestation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import time
import uuid

from app.core.config import Settings
from app.schemas.tracking import GPSLocationCreate


class GPSProvenanceError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedGPSMessage:
    device_id: uuid.UUID
    nonce: uuid.UUID


def canonical_message(session_id: uuid.UUID, device_id: uuid.UUID, nonce: uuid.UUID,
                      sent_at: int, payload: GPSLocationCreate) -> bytes:
    data = json.dumps(payload.model_dump(mode='json'), sort_keys=True,
                      separators=(',', ':'), ensure_ascii=True)
    return f"gps-v1\n{session_id}\n{device_id}\n{nonce}\n{sent_at}\n{data}".encode('utf-8')


def verify_gps_signature(settings: Settings, *, session_id: uuid.UUID, vehicle_id: uuid.UUID,
                         payload: GPSLocationCreate, device_id: str, nonce: str,
                         sent_at: str, signature: str, now: int | None = None) -> VerifiedGPSMessage:
    try:
        did, n = uuid.UUID(device_id), uuid.UUID(nonce)
        at = int(sent_at)
        if str(at) != sent_at or abs((int(time.time()) if now is None else now) - at) > 30:
            raise ValueError('out-of-window timestamp')
        if len(signature) != 64:
            raise ValueError('bad signature length')
        supplied = bytes.fromhex(signature)
        devices = json.loads(settings.gps_trusted_devices_json)
        if not isinstance(devices, dict) or not isinstance(devices.get(str(did)), dict):
            raise ValueError('unregistered device')
        device = devices[str(did)]
        if uuid.UUID(str(device['vehicle_id'])) != vehicle_id:
            raise ValueError('device does not belong to vehicle')
        secret = bytes.fromhex(device['secret_hex'])
        if len(secret) < 32:
            raise ValueError('weak device secret')
        if payload.source.value not in {'gps_device', 'mobile_app'}:
            raise ValueError('source is not a trusted GPS device')
    except (ValueError, KeyError, TypeError, OverflowError, json.JSONDecodeError) as exc:
        raise GPSProvenanceError('Untrusted GPS device signature or binding.') from exc
    expected = hmac.digest(secret, canonical_message(session_id, did, n, at, payload), hashlib.sha256)
    if not hmac.compare_digest(supplied, expected):
        raise GPSProvenanceError('Untrusted GPS device signature or binding.')
    return VerifiedGPSMessage(device_id=did, nonce=n)
