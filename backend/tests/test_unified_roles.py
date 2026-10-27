from app.models.roles import UserRole


def test_only_unified_operational_roles_exist():
    assert [role.value for role in UserRole] == ["hospital", "collector", "facility", "admin"]
