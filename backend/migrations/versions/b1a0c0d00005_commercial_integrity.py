"""Commercial workflow integrity, organization ownership and durable worker leases.

Revision ID: b1a0c0d00005
Revises: b1a0c0d00004

Before deploying, back up the database and review existing conflicting active
routes / confirmed matches: partial unique index creation refuses corrupted
history rather than silently deleting records.
"""
from alembic import op
import sqlalchemy as sa
import hashlib

revision = "b1a0c0d00005"
down_revision = "b1a0c0d00004"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("hospital_profiles", "facility_profiles"):
        op.add_column(table, sa.Column("organization_id", sa.UUID(),
                                       sa.ForeignKey("organizations.id"), nullable=True))
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
        # Backfill only unambiguous company ownership. Unresolved rows remain
        # null, never silently attributed to the wrong company.
        kind = "HOSPITAL" if table == "hospital_profiles" else "TREATMENT_FACILITY"
        op.execute(sa.text(f"""
            UPDATE {table} p SET organization_id = o.id
            FROM organizations o WHERE o.owner_user_id = p.user_id
              AND o.org_type = :kind
              AND (SELECT count(*) FROM organizations x
                   WHERE x.owner_user_id = p.user_id AND x.org_type = :kind) = 1
        """).bindparams(kind=kind))
    op.add_column("event_outbox", sa.Column("lease_owner", sa.String(64), nullable=True))
    op.add_column("event_outbox", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_event_outbox_lease_expires_at", "event_outbox", ["lease_expires_at"])

    # Historical invitation tokens were stored in clear text. Existing
    # issued links keep working while the database retains only a digest.
    connection = op.get_bind()
    for row_id, raw_token in connection.execute(sa.text(
        "SELECT id, token FROM organization_invitations")).fetchall():
        connection.execute(sa.text(
            "UPDATE organization_invitations SET token = :digest WHERE id = :id"),
            {"id": row_id, "digest": hashlib.sha256(raw_token.encode()).hexdigest()})

    # Preserve existing links; don't enforce NOT NULL until legacy records are
    # manually attributed. Future API creates organization-scoped vehicles.
    op.execute(sa.text("""
        UPDATE vehicles v SET organization_id = o.id
        FROM organizations o WHERE v.organization_id IS NULL
            AND o.org_type = 'COLLECTION_COMPANY'
            AND o.owner_user_id = v.assigned_collector_id
            AND (SELECT count(*) FROM organizations x
                WHERE x.owner_user_id = v.assigned_collector_id
                AND x.org_type = 'COLLECTION_COMPANY') = 1
    """))

    # Assert data is clean instead of masking historical conflicting states.
    op.execute("CREATE UNIQUE INDEX uq_routes_one_active_per_vehicle ON routes(vehicle_id) WHERE status = 'ACTIVE'")
    op.execute("CREATE UNIQUE INDEX uq_matching_one_confirmed_per_batch ON matching_records(waste_record_id) WHERE is_confirmed IS TRUE")


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_matching_one_confirmed_per_batch")
    op.execute("DROP INDEX IF EXISTS uq_routes_one_active_per_vehicle")
    op.drop_index("ix_event_outbox_lease_expires_at", table_name="event_outbox")
    op.drop_column("event_outbox", "lease_expires_at")
    op.drop_column("event_outbox", "lease_owner")
    for table in ("hospital_profiles", "facility_profiles"):
        op.drop_index(f"ix_{table}_organization_id", table_name=table)
        op.drop_column(table, "organization_id")
    # Hashed invitations intentionally stay hashed; impossible to recover plaintext.
