"""No provider/DB dependencies; direct contract checks for merchant validation."""
from dataclasses import replace
from decimal import Decimal
import pytest
from app.services.payment_gateway import (
    VerifiedPayment, GatewayFailure, assert_verified_matches_intent, MockGateway,
)
from app.core.config import Settings

GOOD = VerifiedPayment(reference="MW-TEST-123", provider_transaction_id="BANK123",
                       amount_bdt=Decimal("6100.00"), currency="BDT",
                       status="VALID", risk_level=0, channel="bkash")


def test_verified_response_accepts_matching_safe_bdt():
    assert_verified_matches_intent(GOOD, expected_reference=GOOD.reference,
                                   expected_amount=Decimal("6100.00"))


@pytest.mark.parametrize("change", [
    {"reference":"OTHER"}, {"reference":""}, {"amount_bdt":Decimal("6100.01")},
    {"currency":"USD"}, {"risk_level":1}, {"provider_transaction_id":""},
    {"status":"FAILED"},
])
def test_verified_response_rejects_mismatch(change):
    with pytest.raises(GatewayFailure):
        assert_verified_matches_intent(replace(GOOD, **change),
                                       expected_reference=GOOD.reference,
                                       expected_amount=Decimal("6100.00"))


def test_mock_never_verifies_actual_provider_payment():
    with pytest.raises(GatewayFailure):
        MockGateway().verify(provider_validation_id="anything")


def test_production_fails_closed_on_insecure_demo_and_sandbox():
    base = dict(environment="production", debug=False,
                jwt_secret_key="a-unique-secret-that-exceeds-thirty-two-bytes",
                auth_cookie_secure=True, payment_live_approved=True,
                payment_public_base_url="https://payments.example.org",
                frontend_public_base_url="https://medwaste.example.org")
    for mode in ("mock", "sandbox"):
        with pytest.raises(ValueError):
            Settings(**base, payment_mode=mode)
    Settings(**base, payment_mode="live")
    with pytest.raises(ValueError):
        Settings(**{**base, "auth_cookie_secure": False}, payment_mode="live")
