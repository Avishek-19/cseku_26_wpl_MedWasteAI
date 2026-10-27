import enum


class UserRole(str, enum.Enum):
    """Roles supported by the platform. Recycling is a facility capability, not a user role."""

    HOSPITAL = "hospital"
    COLLECTOR = "collector"
    FACILITY = "facility"
    ADMIN = "admin"
