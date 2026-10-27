"""phase 2 transport tracking foundation

Revision ID: 7a91c4d2e6f0
Revises: fd45a1c2b789
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "7a91c4d2e6f0"
down_revision: Union[str, Sequence[str], None] = "ef78a9b1c234"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tracking_session_status = postgresql.ENUM(
        "CREATED", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED", "OFFLINE",
        name="tracking_session_status",
        create_type=False,
    )
    location_source = postgresql.ENUM(
        "SIMULATOR", "GPS_DEVICE", "MOBILE_APP", "MANUAL",
        name="location_source",
        create_type=False,
    )
    gps_anomaly_type = postgresql.ENUM(
        "INVALID_COORDINATES", "IMPOSSIBLE_SPEED", "LARGE_JUMP", "STALE_TIMESTAMP",
        name="gps_anomaly_type",
        create_type=False,
    )
    route_status = postgresql.ENUM(
        "DRAFT", "READY", "ACTIVE", "COMPLETED", "CANCELLED",
        name="route_status",
        create_type=False,
    )
    route_stop_status = postgresql.ENUM(
        "PENDING", "EN_ROUTE", "ARRIVED", "COLLECTED", "SKIPPED", "CANCELLED",
        name="route_stop_status",
        create_type=False,
    )

    bind = op.get_bind()
    for enum_type in (
        tracking_session_status,
        location_source,
        gps_anomaly_type,
        route_status,
        route_stop_status,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "tracking_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pickup_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", tracking_session_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_location_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pickup_id"], ["pickup_requests.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_tracking_sessions_vehicle_id", "tracking_sessions", ["vehicle_id"])
    op.create_index("ix_tracking_sessions_pickup_id", "tracking_sessions", ["pickup_id"])
    op.create_index("ix_tracking_sessions_status", "tracking_sessions", ["status"])
    op.create_index("ix_tracking_sessions_last_location_at", "tracking_sessions", ["last_location_at"])

    op.create_table(
        "tracking_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tracking_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("speed_kmh", sa.Numeric(7, 2), nullable=True),
        sa.Column("heading_degrees", sa.Numeric(6, 2), nullable=True),
        sa.Column("accuracy_m", sa.Numeric(8, 2), nullable=True),
        sa.Column("altitude_m", sa.Numeric(9, 2), nullable=True),
        sa.Column("source", location_source, nullable=False),
        sa.Column("anomaly_type", gps_anomaly_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tracking_session_id"], ["tracking_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_tracking_locations_tracking_session_id", "tracking_locations", ["tracking_session_id"])
    op.create_index("ix_tracking_locations_vehicle_id", "tracking_locations", ["vehicle_id"])
    op.create_index("ix_tracking_locations_timestamp", "tracking_locations", ["timestamp"])
    op.create_index("ix_tracking_locations_session_timestamp", "tracking_locations", ["tracking_session_id", "timestamp"])
    op.create_index("ix_tracking_locations_vehicle_timestamp", "tracking_locations", ["vehicle_id", "timestamp"])

    op.create_table(
        "routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracking_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", route_status, nullable=False),
        sa.Column("is_optimized", sa.Boolean(), nullable=False),
        sa.Column("total_distance_km", sa.Numeric(10, 2), nullable=True),
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("origin_latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("origin_longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("destination_latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("destination_longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tracking_session_id"], ["tracking_sessions.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_routes_vehicle_id", "routes", ["vehicle_id"])
    op.create_index("ix_routes_tracking_session_id", "routes", ["tracking_session_id"])
    op.create_index("ix_routes_status", "routes", ["status"])
    op.create_index("ix_routes_vehicle_status", "routes", ["vehicle_id", "status"])

    op.create_table(
        "route_stops",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pickup_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("status", route_stop_status, nullable=False),
        sa.Column("estimated_arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pickup_id"], ["pickup_requests.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("route_id", "sequence", name="uq_route_stops_route_sequence"),
        sa.UniqueConstraint("route_id", "pickup_id", name="uq_route_stops_route_pickup"),
    )
    op.create_index("ix_route_stops_route_id", "route_stops", ["route_id"])
    op.create_index("ix_route_stops_pickup_id", "route_stops", ["pickup_id"])
    op.create_index("ix_route_stops_route_status", "route_stops", ["route_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_route_stops_route_status", table_name="route_stops")
    op.drop_index("ix_route_stops_pickup_id", table_name="route_stops")
    op.drop_index("ix_route_stops_route_id", table_name="route_stops")
    op.drop_table("route_stops")

    op.drop_index("ix_routes_vehicle_status", table_name="routes")
    op.drop_index("ix_routes_status", table_name="routes")
    op.drop_index("ix_routes_tracking_session_id", table_name="routes")
    op.drop_index("ix_routes_vehicle_id", table_name="routes")
    op.drop_table("routes")

    op.drop_index("ix_tracking_locations_vehicle_timestamp", table_name="tracking_locations")
    op.drop_index("ix_tracking_locations_session_timestamp", table_name="tracking_locations")
    op.drop_index("ix_tracking_locations_timestamp", table_name="tracking_locations")
    op.drop_index("ix_tracking_locations_vehicle_id", table_name="tracking_locations")
    op.drop_index("ix_tracking_locations_tracking_session_id", table_name="tracking_locations")
    op.drop_table("tracking_locations")

    op.drop_index("ix_tracking_sessions_last_location_at", table_name="tracking_sessions")
    op.drop_index("ix_tracking_sessions_status", table_name="tracking_sessions")
    op.drop_index("ix_tracking_sessions_pickup_id", table_name="tracking_sessions")
    op.drop_index("ix_tracking_sessions_vehicle_id", table_name="tracking_sessions")
    op.drop_table("tracking_sessions")

    bind = op.get_bind()
    for enum_name in ("route_stop_status", "route_status", "gps_anomaly_type", "location_source", "tracking_session_status"):
        sa.Enum(name=enum_name).drop(bind, checkfirst=True)
