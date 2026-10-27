import math
from datetime import datetime, timezone
from decimal import Decimal

from app.core.config import Settings
from app.models.tracking import GPSAnomalyType, TrackingLocation


class GPSValidationError(ValueError):
    """Raised when a GPS point is invalid and must not be stored."""


class GPSValidationService:
    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def haversine_km(lat1: Decimal, lon1: Decimal, lat2: Decimal, lon2: Decimal) -> float:
        radius = 6371.0088
        p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
        dphi = math.radians(float(lat2 - lat1))
        dlambda = math.radians(float(lon2 - lon1))
        a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
        return 2 * radius * math.asin(math.sqrt(a))

    def validate(self, *, latitude: Decimal, longitude: Decimal, speed_kmh: Decimal | None) -> None:
        lat = float(latitude)
        lon = float(longitude)
        if not math.isfinite(lat) or not (-90 <= lat <= 90):
            raise GPSValidationError("Latitude must be between -90 and 90 degrees.")
        if not math.isfinite(lon) or not (-180 <= lon <= 180):
            raise GPSValidationError("Longitude must be between -180 and 180 degrees.")
        if speed_kmh is not None:
            speed = float(speed_kmh)
            if not math.isfinite(speed) or speed < 0:
                raise GPSValidationError("GPS speed cannot be negative or non-finite.")
            if speed > self.settings.gps_max_speed_kmh:
                raise GPSValidationError("GPS speed exceeds the configured maximum speed.")

    def classify_against_previous(self, *, current_timestamp: datetime, latitude: Decimal, longitude: Decimal,
                                  speed_kmh: Decimal | None, previous: TrackingLocation | None) -> GPSAnomalyType | None:
        if current_timestamp.tzinfo is None or current_timestamp.utcoffset() is None:
            return GPSAnomalyType.STALE_TIMESTAMP
        if previous is None:
            return None

        # Some SQLite test adapters return naive timestamps even for
        # DateTime(timezone=True); the application stores UTC, so interpret
        # these historical values as UTC rather than crashing on comparison.
        previous_timestamp = previous.timestamp
        if previous_timestamp.tzinfo is None or previous_timestamp.utcoffset() is None:
            previous_timestamp = previous_timestamp.replace(tzinfo=timezone.utc)
        if current_timestamp <= previous_timestamp:
            return GPSAnomalyType.STALE_TIMESTAMP

        distance_km = self.haversine_km(previous.latitude, previous.longitude, latitude, longitude)
        elapsed_hours = (current_timestamp - previous_timestamp).total_seconds() / 3600
        if elapsed_hours <= 0:
            return GPSAnomalyType.STALE_TIMESTAMP
        implied_speed = distance_km / elapsed_hours
        if distance_km > self.settings.gps_max_jump_km:
            return GPSAnomalyType.LARGE_JUMP
        if implied_speed > self.settings.gps_max_speed_kmh:
            return GPSAnomalyType.IMPOSSIBLE_SPEED
        return None
