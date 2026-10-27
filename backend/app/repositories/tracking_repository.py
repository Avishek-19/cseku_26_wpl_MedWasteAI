import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tracking import TrackingLocation, TrackingSession, TrackingSessionStatus


class TrackingRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_session(self, session: TrackingSession) -> TrackingSession:
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_session(self, session_id: uuid.UUID) -> TrackingSession | None:
        return self.db.get(TrackingSession, session_id)

    def get_active_for_vehicle(self, vehicle_id: uuid.UUID) -> TrackingSession | None:
        stmt = select(TrackingSession).where(
            TrackingSession.vehicle_id == vehicle_id,
            TrackingSession.status.in_([TrackingSessionStatus.CREATED, TrackingSessionStatus.ACTIVE, TrackingSessionStatus.PAUSED]),
        ).order_by(TrackingSession.created_at.desc())
        return self.db.execute(stmt).scalars().first()

    def set_current_route(self, session: TrackingSession, route_id: uuid.UUID | None) -> TrackingSession:
        session.current_route_id = route_id
        return self.save_session(session)

    def save_session(self, session: TrackingSession) -> TrackingSession:
        self.db.commit()
        self.db.refresh(session)
        return session

    def create_location(self, location: TrackingLocation, *, commit: bool = True) -> TrackingLocation:
        self.db.add(location)
        if commit:
            self.db.commit()
            self.db.refresh(location)
        else:
            # Assign the location ID without making GPS data durable before
            # route progression, nonce and chain-of-custody changes succeed.
            self.db.flush()
        return location

    def get_latest_location(self, vehicle_id: uuid.UUID) -> TrackingLocation | None:
        stmt = select(TrackingLocation).where(TrackingLocation.vehicle_id == vehicle_id).order_by(
            TrackingLocation.timestamp.desc()
        ).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_latest_location_for_session(self, session_id: uuid.UUID, *, trusted_only: bool = False) -> TrackingLocation | None:
        stmt = select(TrackingLocation).where(TrackingLocation.tracking_session_id == session_id)
        if trusted_only:
            # Unsigned browser points and signed-but-anomalous points must not
            # corrupt the speed/jump baseline of authenticated telemetry.
            stmt = stmt.where(
                TrackingLocation.provenance_verified.is_(True),
                TrackingLocation.anomaly_type.is_(None),
            )
        stmt = stmt.order_by(TrackingLocation.timestamp.desc(), TrackingLocation.created_at.desc()).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()
