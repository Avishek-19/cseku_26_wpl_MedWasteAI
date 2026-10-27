"""Dhaka-local pickup scheduling; all persisted timestamps are UTC-aware.

Holiday dates are operator-configured. Without a verified local calendar the
system does not pretend to know that every public holiday is closed.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from app.models.vehicle import Vehicle
from app.models.waste_enums import PickupPriority

DHAKA = ZoneInfo('Asia/Dhaka')

@dataclass
class SchedulingResult:
    vehicle: Vehicle | None
    scheduled_at: datetime
    explanation: str


def compute_scheduled_at(*, priority: PickupPriority, now: datetime | None = None,
                         requested_at: datetime | None = None, requested_end_at: datetime | None = None,
                         open_hour: int = 9, close_hour: int = 17,
                         closed_weekdays: frozenset[int] = frozenset({4}),
                         holidays: frozenset[date] = frozenset()) -> datetime:
    if not (0 <= open_hour < close_hour <= 24):
        raise ValueError('Business hours must satisfy 0 <= open < close <= 24')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Current time must be timezone-aware')
    for value in (requested_at, requested_end_at):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError('Requested pickup window must be timezone-aware')
    now = now.astimezone(timezone.utc)
    if requested_at and requested_end_at and requested_end_at <= requested_at:
        raise ValueError('Pickup window end must occur after start')
    # Emergency and urgent transport can operate outside contracted business
    # hours; the requested earliest time is still respected.
    if priority in {PickupPriority.EMERGENCY, PickupPriority.URGENT}:
        result = max(now, requested_at.astimezone(timezone.utc)) if requested_at else now
    else:
        first_day = now.astimezone(DHAKA).date() + timedelta(days=1)
        earliest = max(
            datetime.combine(first_day, time(open_hour), tzinfo=DHAKA),
            requested_at.astimezone(DHAKA) if requested_at else datetime.combine(first_day, time(open_hour), tzinfo=DHAKA),
        )
        candidate = earliest
        for _ in range(366):
            day = candidate.date()
            opening = datetime.combine(day, time(open_hour), tzinfo=DHAKA)
            closing = datetime.combine(day + timedelta(days=1), time.min, tzinfo=DHAKA) if close_hour == 24 else datetime.combine(day, time(close_hour), tzinfo=DHAKA)
            if day.weekday() not in closed_weekdays and day not in holidays:
                slot = max(candidate, opening)
                if slot < closing:
                    candidate = slot
                    break
            candidate = datetime.combine(day + timedelta(days=1), time(open_hour), tzinfo=DHAKA)
        else:
            raise ValueError('No eligible business time found within one year')
        result = candidate.astimezone(timezone.utc)
    if requested_end_at is not None and result > requested_end_at.astimezone(timezone.utc):
        raise ValueError('No feasible pickup time fits the requested window and business calendar')
    return result


def select_vehicle(*, candidates: list[Vehicle], required_capacity: Decimal) -> Vehicle | None:
    eligible = [v for v in candidates if Decimal(str(v.capacity_kg)) >= required_capacity]
    return min(eligible, key=lambda v: v.capacity_kg) if eligible else None


def schedule_pickup(*, priority: PickupPriority, required_capacity: Decimal,
                    candidate_vehicles: list[Vehicle], requested_at: datetime | None = None,
                    requested_end_at: datetime | None = None) -> SchedulingResult:
    from app.core.config import get_settings
    cfg = get_settings()
    weekdays = frozenset(int(x.strip()) for x in cfg.pickup_closed_weekdays.split(',') if x.strip())
    holidays = frozenset(date.fromisoformat(x.strip()) for x in cfg.pickup_holidays_bd.split(',') if x.strip())
    scheduled_at = compute_scheduled_at(priority=priority, requested_at=requested_at,
        requested_end_at=requested_end_at, open_hour=cfg.pickup_business_open_hour,
        close_hour=cfg.pickup_business_close_hour, closed_weekdays=weekdays,
        holidays=holidays)
    vehicle = select_vehicle(candidates=candidate_vehicles, required_capacity=required_capacity)
    if vehicle is None:
        explanation = 'Pickup queued: no eligible vehicle currently has the required remaining capacity.'
    else:
        explanation = f'Planned vehicle {vehicle.vehicle_code}; actual departure requires driver route-start confirmation.'
    return SchedulingResult(vehicle, scheduled_at, explanation)
