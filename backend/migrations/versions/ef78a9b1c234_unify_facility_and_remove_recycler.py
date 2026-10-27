"""Make Waste Processing Facility the only destination organization.

Existing recycler profiles are migrated into facility profiles (with Recycling
as a processing capability) before the legacy recycler tables/columns and enum
values are removed. This preserves existing operational data where possible.
"""
from alembic import op
import sqlalchemy as sa

revision = "ef78a9b1c234"
down_revision = "fd45a1c2b789"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Facility profile supports free-form authorized services as well as the
    # standard processing service codes used by deterministic matching.
    op.add_column(
        "facility_profiles",
        sa.Column("other_services", sa.JSON(), nullable=False, server_default="[]"),
    )

    # Migrate any legacy recycler organization into the unified facility model.
    op.execute(
        sa.text(
            """
            INSERT INTO facility_profiles
                (id, user_id, name, registration_number, contact_person, phone,
                 address_line, city, region, postal_code, capacity_kg,
                 current_utilization_kg, is_verified, processing_services,
                 other_services, availability_status, facility_type,
                 created_at, updated_at)
            SELECT rp.id, rp.user_id, rp.name, rp.registration_number,
                   rp.contact_person, rp.phone, rp.address_line, rp.city,
                   rp.region, rp.postal_code, rp.capacity_kg,
                   rp.current_utilization_kg, rp.is_verified,
                   '["RECYCLING"]', '[]', 'available',
                   'Waste Processing Facility', rp.created_at, rp.updated_at
            FROM recycler_profiles rp
            WHERE NOT EXISTS (
                SELECT 1 FROM facility_profiles fp WHERE fp.user_id = rp.user_id
            )
            """
        )
    )

    # Preserve accepted categories for migrated organizations.
    op.execute(
        sa.text(
            """
            INSERT INTO facility_accepted_categories (id, facility_id, category_id, created_at)
            SELECT rac.id, fp.id, rac.category_id, rac.created_at
            FROM recycler_accepted_categories rac
            JOIN recycler_profiles rp ON rp.id = rac.recycler_id
            JOIN facility_profiles fp ON fp.user_id = rp.user_id
            ON CONFLICT (facility_id, category_id) DO NOTHING
            """
        )
    )

    # Move any historical confirmed recycler destination to the matching
    # unified facility record before dropping the legacy foreign key/column.
    op.execute(
        sa.text(
            """
            UPDATE matching_records m
            SET confirmed_facility_id = fp.id,
                destination_type = 'WASTE_PROCESSING_FACILITY',
                processing_method = COALESCE(m.processing_method, 'RECYCLING')
            FROM recycler_profiles rp
            JOIN facility_profiles fp ON fp.user_id = rp.user_id
            WHERE m.confirmed_recycler_id = rp.id
            """
        )
    )
    op.execute(
        sa.text("UPDATE matching_records SET destination_type = 'WASTE_PROCESSING_FACILITY'")
    )

    # Remove the legacy recycler foreign key/column.
    op.drop_constraint(
        "matching_records_confirmed_recycler_id_fkey",
        "matching_records",
        type_="foreignkey",
    )
    op.drop_column("matching_records", "confirmed_recycler_id")

    op.drop_table("recycler_accepted_categories")
    op.drop_index("ix_recycler_profiles_user_id", table_name="recycler_profiles")
    op.drop_table("recycler_profiles")

    # Recreate enums without the retired role/destination values. Existing
    # recycler users were migrated above, so no live row is left behind.
    op.execute(
        sa.text(
            """
            ALTER TABLE users ALTER COLUMN role TYPE text USING role::text;
            UPDATE users SET role = 'FACILITY' WHERE role = 'RECYCLER';
            DROP TYPE user_role;
            CREATE TYPE user_role AS ENUM ('HOSPITAL','COLLECTOR','FACILITY','ADMIN');
            ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role;
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE matching_records ALTER COLUMN destination_type TYPE text USING destination_type::text;
            DROP TYPE destination_type;
            CREATE TYPE destination_type AS ENUM ('WASTE_PROCESSING_FACILITY');
            ALTER TABLE matching_records ALTER COLUMN destination_type TYPE destination_type USING destination_type::destination_type;
            """
        )
    )


def downgrade() -> None:
    # Recreate the legacy schema shape. Migrated facility data is intentionally
    # kept in facility_profiles; an automatic split back into organizations
    # would be lossy and unsafe. Legacy tables are recreated empty.
    op.execute(sa.text("ALTER TABLE matching_records ALTER COLUMN destination_type TYPE text USING destination_type::text"))
    op.execute(sa.text("DROP TYPE destination_type"))
    op.execute(sa.text("CREATE TYPE destination_type AS ENUM ('FACILITY','RECYCLER','WASTE_PROCESSING_FACILITY')"))
    op.execute(sa.text("ALTER TABLE matching_records ALTER COLUMN destination_type TYPE destination_type USING destination_type::destination_type"))

    op.execute(sa.text("ALTER TABLE users ALTER COLUMN role TYPE text USING role::text"))
    op.execute(sa.text("DROP TYPE user_role"))
    op.execute(sa.text("CREATE TYPE user_role AS ENUM ('HOSPITAL','COLLECTOR','FACILITY','RECYCLER','ADMIN')"))
    op.execute(sa.text("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role"))

    op.create_table(
        "recycler_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("registration_number", sa.String(length=100), nullable=False),
        sa.Column("contact_person", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("address_line", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("region", sa.String(length=120), nullable=False),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.Column("capacity_kg", sa.Numeric(10, 2), nullable=False),
        sa.Column("current_utilization_kg", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recycler_profiles_user_id", "recycler_profiles", ["user_id"], unique=True)
    op.create_table(
        "recycler_accepted_categories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recycler_id", sa.UUID(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["waste_categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recycler_id"], ["recycler_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recycler_id", "category_id"),
    )
    op.add_column("matching_records", sa.Column("confirmed_recycler_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "matching_records_confirmed_recycler_id_fkey",
        "matching_records", "recycler_profiles", ["confirmed_recycler_id"], ["id"], ondelete="SET NULL",
    )
    op.drop_column("facility_profiles", "other_services")
