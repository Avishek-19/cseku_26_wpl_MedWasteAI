from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.models.tracking import TrackingLocation
from app.services.gps_validation_service import GPSValidationError, GPSValidationService


def validator():
    return GPSValidationService(Settings(gps_max_speed_kmh=120, gps_max_jump_km=5))


def test_valid_coordinates_are_accepted():
    validator().validate(latitude=Decimal("22.8150"), longitude=Decimal("89.5500"), speed_kmh=Decimal("34"))


def test_invalid_latitude_is_rejected():
    with pytest.raises(GPSValidationError):
        validator().validate(latitude=Decimal("91"), longitude=Decimal("89.5500"), speed_kmh=None)


def test_impossible_speed_is_rejected():
    with pytest.raises(GPSValidationError):
        validator().validate(latitude=Decimal("22.8"), longitude=Decimal("89.5"), speed_kmh=Decimal("121"))


def test_large_jump_is_flagged():
    now = datetime.now(timezone.utc)
    previous = TrackingLocation(
        tracking_session_id=None, vehicle_id=None,
        latitude=Decimal("22.8150"), longitude=Decimal("89.5500"), timestamp=now,
        speed_kmh=None, heading_degrees=None, accuracy_m=None, altitude_m=None,
        source="MANUAL", anomaly_type=None,
    )
    anomaly = validator().classify_against_previous(
        current_timestamp=now + timedelta(minutes=1),
        latitude=Decimal("22.9000"), longitude=Decimal("90.3000"),
        speed_kmh=None, previous=previous,
    )
    assert anomaly.value == "large_jump"


def test_negative_speed_is_rejected():
    with pytest.raises(GPSValidationError):
        validator().validate(latitude=Decimal("22.8"), longitude=Decimal("89.5"), speed_kmh=Decimal("-1"))


def test_non_finite_coordinate_is_rejected():
    with pytest.raises(GPSValidationError):
        validator().validate(latitude=Decimal("NaN"), longitude=Decimal("89.5"), speed_kmh=None)
