"""Gateway-agnostic initiation and server-side verification.

Demo mode (PAYMENT_MODE=mock):
  - User picks bKash / Nagad / Rocket in the UI.
  - No real PIN, OTP, or merchant credentials required.
  - Completing a demo payment is clearly labeled and only works in
    development/test with PAYMENT_MODE=mock.

Sandbox/Live:
  - SSLCOMMERZ hosted checkout (official aggregator).
  - Never invent direct unofficial bKash/Nagad/Rocket APIs.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse

import httpx

from app.services.business_finance import money


class GatewayFailure(Exception):
    pass


@dataclass(frozen=True)
class GatewaySession:
    redirect_url: str
    session_id: str
    channel: str = "demo"
    is_demo: bool = False


@dataclass(frozen=True)
class VerifiedPayment:
    reference: str
    provider_transaction_id: str
    amount_bdt: Decimal
    currency: str
    status: str
    risk_level: int
    channel: str = "unknown"


def assert_verified_matches_intent(
    verified: VerifiedPayment, *, expected_reference: str,
    expected_amount: Decimal, expected_currency: str = "BDT",
) -> None:
    """Fail-closed verification of the official server-to-server provider response.

    Validation ID must have been checked online by the gateway adapter first;
    caller must additionally enforce unique provider transaction ID and a
    locked, unpaid target before mutating the journal.
    """
    if verified.status not in {"VALID", "VALIDATED"}:
        raise GatewayFailure("Provider did not confirm a valid transaction")
    if not expected_reference or verified.reference != expected_reference:
        raise GatewayFailure("Verified merchant reference is missing or mismatched")
    if money(verified.amount_bdt) != money(expected_amount):
        raise GatewayFailure("Verified transaction amount mismatches the payment intent")
    if verified.currency.upper() != expected_currency:
        raise GatewayFailure("Verified transaction has the wrong currency")
    if verified.risk_level != 0:
        raise GatewayFailure("Provider flagged the transaction high risk; hold for review")
    if not verified.provider_transaction_id.strip():
        raise GatewayFailure("Verified provider transaction ID is missing")


class PaymentGateway(ABC):
    @abstractmethod
    def initiate(
        self,
        *,
        reference: str,
        amount: Decimal,
        correlation: str,
        customer: dict[str, str],
        callbacks: dict[str, str],
        channel: str = "bkash",
    ) -> GatewaySession:
        ...

    @abstractmethod
    def verify(self, *, provider_validation_id: str) -> VerifiedPayment:
        ...


class MockGateway(PaymentGateway):
    """Local DEMO flow for bKash / Nagad / Rocket.

    - No real money movement.
    - No PIN / OTP / merchant account required.
    - UI shows a clear DEMO badge.
    - Completion is handled by POST /payments/mock/complete (dev/test only).
    """

    CHANNEL_LABELS = {
        "bkash": "bKash (DEMO)",
        "nagad": "Nagad (DEMO)",
        "rocket": "Rocket (DEMO)",
    }

    def initiate(
        self,
        *,
        reference: str,
        amount: Decimal,
        correlation: str,
        customer: dict[str, str],
        callbacks: dict[str, str],
        channel: str = "bkash",
    ) -> GatewaySession:
        ch = (channel or "bkash").lower()
        if ch not in self.CHANNEL_LABELS:
            ch = "bkash"
        # Frontend stays on billing page and shows demo confirm panel.
        return GatewaySession(
            redirect_url=f"/dashboard/billing?demo_ref={reference}&channel={ch}&demo=1",
            session_id=f"DEMO-{ch.upper()}-{reference}",
            channel=ch,
            is_demo=True,
        )

    def verify(self, *, provider_validation_id: str) -> VerifiedPayment:
        raise GatewayFailure(
            "Mock/DEMO gateway cannot validate a real provider payment. "
            "Use POST /payments/mock/complete in development only."
        )


class SSLCommerzGateway(PaymentGateway):
    SANDBOX = "https://sandbox.sslcommerz.com"
    LIVE = "https://securepay.sslcommerz.com"

    def __init__(self, *, mode: str, store_id: str, store_password: str):
        if mode not in {"sandbox", "live"} or not store_id or not store_password:
            raise GatewayFailure("Gateway not correctly configured")
        if store_id.startswith("YOUR_") or store_password.startswith("YOUR_"):
            raise GatewayFailure("Real sandbox/live merchant credentials required")
        self.root = self.LIVE if mode == "live" else self.SANDBOX
        self.store_id = store_id
        self.store_password = store_password
        self.mode = mode

    def initiate(
        self,
        *,
        reference: str,
        amount: Decimal,
        correlation: str,
        customer: dict[str, str],
        callbacks: dict[str, str],
        channel: str = "bkash",
    ) -> GatewaySession:
        if money(amount) <= 0:
            raise GatewayFailure("Payment amount must be positive")
        # Preferred channel is a soft hint; SSLCOMMERZ hosted page shows
        # enabled MFS options. We never invent direct MFS endpoints.
        payload = {
            "store_id": self.store_id,
            "store_passwd": self.store_password,
            "total_amount": str(money(amount)),
            "currency": "BDT",
            "tran_id": reference,
            "success_url": callbacks["success"],
            "fail_url": callbacks["fail"],
            "cancel_url": callbacks["cancel"],
            "ipn_url": callbacks["ipn"],
            "shipping_method": "NO",
            "product_name": "MedWaste service",
            "product_category": "waste_management",
            "product_profile": "general",
            "cus_name": customer["name"],
            "cus_email": customer["email"],
            "cus_add1": customer["address"],
            "cus_city": customer["city"],
            "cus_country": "Bangladesh",
            "cus_phone": customer["phone"],
            "value_a": correlation,
            "value_b": (channel or "bkash").lower(),
        }
        try:
            with httpx.Client(timeout=12.0) as client:
                response = client.post(self.root + "/gwprocess/v4/api.php", data=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GatewayFailure("Gateway session could not be initiated") from exc
        if not isinstance(data, dict):
            raise GatewayFailure("Invalid gateway response")
        url = data.get("GatewayPageURL")
        session = data.get("sessionkey") or data.get("sessionKey")
        parsed = urlparse(url) if isinstance(url, str) else None
        if (data.get("status") != "SUCCESS" or not parsed or parsed.scheme != "https"
                or not parsed.hostname or not parsed.hostname.endswith(".sslcommerz.com")
                or parsed.username or parsed.password or not isinstance(session, str) or not session):
            raise GatewayFailure("Gateway did not issue a usable HTTPS session")
        return GatewaySession(
            redirect_url=url,
            session_id=session,
            channel=(channel or "bkash").lower(),
            is_demo=False,
        )

    def verify(self, *, provider_validation_id: str) -> VerifiedPayment:
        if len(provider_validation_id) > 120 or not provider_validation_id:
            raise GatewayFailure("Invalid provider validation ID")
        try:
            with httpx.Client(timeout=12.0) as client:
                resp = client.get(
                    self.root + "/validator/api/validationserverAPI.php",
                    params={
                        "val_id": provider_validation_id,
                        "store_id": self.store_id,
                        "store_passwd": self.store_password,
                        "v": "1",
                        "format": "json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GatewayFailure("Gateway status verification unavailable") from exc
        if not isinstance(data, dict) or data.get("status") not in {"VALID", "VALIDATED"}:
            raise GatewayFailure("Gateway has not confirmed payment")
        try:
            amount = money(data.get("amount", "0"))
            if not amount.is_finite():
                raise ValueError("Non-finite payment amount")
            return VerifiedPayment(
                reference=str(data.get("tran_id") or ""),
                provider_transaction_id=str(data.get("bank_tran_id") or ""),
                amount_bdt=amount,
                currency=str(data.get("currency_type") or data.get("currency") or "").upper(),
                status=data["status"], risk_level=int(data.get("risk_level", 1)),
                channel=str(data.get("value_b") or "unknown"))
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise GatewayFailure("Malformed provider validation response") from exc

    def query(self, *, reference: str) -> VerifiedPayment | str | None:
        """Recover lost browser returns/IPNs using the durable merchant reference."""
        try:
            with httpx.Client(timeout=12.0) as client:
                response = client.get(self.root + "/validator/api/merchantTransIDvalidationAPI.php",
                    params={"tran_id": reference, "store_id": self.store_id,
                            "store_passwd": self.store_password, "format": "json"})
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Invalid query response")
            entries = data.get("element", [])
            if not isinstance(entries, list):
                raise ValueError("Invalid transaction list")
            for item in entries:
                if (isinstance(item, dict) and item.get("tran_id") == reference
                        and item.get("status") in {"VALID", "VALIDATED"} and item.get("val_id")):
                    return self.verify(provider_validation_id=str(item["val_id"]))
            for item in entries:
                if isinstance(item, dict) and item.get("tran_id") == reference:
                    status = str(item.get("status") or "").lower()
                    if status in {"failed", "cancelled", "expired"}:
                        return status
            return None
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise GatewayFailure("Gateway reconciliation is temporarily unavailable") from exc
