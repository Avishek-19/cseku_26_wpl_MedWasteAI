import pytest
from fastapi import HTTPException

from app.core.security_config import require_strong_password


def test_password_policy_rejects_short_password():
    with pytest.raises(HTTPException):
        require_strong_password("Short1")


def test_password_policy_requires_character_mix():
    with pytest.raises(HTTPException):
        require_strong_password("alllowercase123")


def test_password_policy_accepts_strong_password():
    require_strong_password("StrongPassword9")
