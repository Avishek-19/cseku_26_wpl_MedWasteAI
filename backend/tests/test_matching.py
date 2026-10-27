"""Focused tests for the unified Waste Processing Facility matching contract.

The API integration suite still lives in the existing project tests; these tests
keep the core deterministic matching policy executable without external APIs.
"""
from dataclasses import dataclass
from decimal import Decimal

from app.rules.matching_rules import filter_by_capacity, rank_candidates
from app.rules.processing_rules import required_processing
from app.models.waste_enums import RiskLevel, SuggestedHandling


@dataclass
class Facility:
    id: str
    name: str
    city: str
    capacity_kg: Decimal
    current_utilization_kg: Decimal
    is_verified: bool
    processing_services: list[str]
    availability_status: str


def eligible(facilities, category, risk, handling, quantity):
    required, acceptable = required_processing(
        category_code=category, risk_level=risk, handling=handling
    )
    compatible = [
        f for f in facilities
        if f.is_verified
        and f.availability_status != "unavailable"
        and any(str(s).upper() in acceptable for s in f.processing_services)
    ]
    return required, filter_by_capacity(candidates=compatible, quantity=quantity)


def test_infectious_waste_selects_best_capable_facility():
    facilities = [
        Facility("a", "SafeMed A", "Dhaka", Decimal("1000"), Decimal("100"), True, ["AUTOCLAVE"], "available"),
        Facility("b", "SafeMed B", "Chattogram", Decimal("1000"), Decimal("100"), True, ["INCINERATION"], "available"),
        Facility("c", "Recovery C", "Dhaka", Decimal("1000"), Decimal("100"), True, ["RECYCLING"], "available"),
    ]
    required, candidates = eligible(
        facilities, "INFECTIOUS", RiskLevel.HIGH, SuggestedHandling.TREAT, Decimal("100")
    )
    ranked = rank_candidates(
        candidates=candidates,
        quantity=Decimal("100"),
        hospital_city="Dhaka",
        hospital_region="Dhaka",
        high_risk=True,
        required_processing=required,
    )
    assert required == "SPECIALIZED_TREATMENT"
    assert {f.id for f in candidates} == {"a", "b"}
    assert ranked[0].candidate.id == "a"


def test_recyclable_waste_can_route_to_recycling_capability_in_same_facility_model():
    facilities = [
        Facility("a", "Integrated Facility", "Dhaka", Decimal("1000"), Decimal("100"), True, ["RECYCLING", "FINAL_DISPOSAL"], "available"),
        Facility("b", "Treatment Only", "Dhaka", Decimal("1000"), Decimal("100"), True, ["AUTOCLAVE"], "available"),
    ]
    required, candidates = eligible(
        facilities, "RECYCLABLE", RiskLevel.LOW, SuggestedHandling.RECYCLE, Decimal("50")
    )
    assert required == "RECYCLING"
    assert [f.id for f in candidates] == ["a"]


def test_incompatible_waste_type_is_rejected():
    facilities = [Facility("a", "Chemical Site", "Dhaka", Decimal("1000"), Decimal("0"), True, ["CHEMICAL_TREATMENT"], "available")]
    _, candidates = eligible(
        facilities, "INFECTIOUS", RiskLevel.HIGH, SuggestedHandling.TREAT, Decimal("10")
    )
    assert candidates == []


def test_capability_mismatch_is_rejected_even_when_category_is_accepted():
    facilities = [Facility("a", "General Site", "Dhaka", Decimal("1000"), Decimal("0"), True, ["FINAL_DISPOSAL"], "available")]
    _, candidates = eligible(
        facilities, "RECYCLABLE", RiskLevel.LOW, SuggestedHandling.RECYCLE, Decimal("10")
    )
    assert candidates == []


def test_capacity_full_is_rejected():
    facilities = [Facility("a", "Full Site", "Dhaka", Decimal("100"), Decimal("95"), True, ["RECYCLING"], "available")]
    _, candidates = eligible(
        facilities, "RECYCLABLE", RiskLevel.LOW, SuggestedHandling.RECYCLE, Decimal("10")
    )
    assert candidates == []


def test_unverified_facility_is_rejected():
    facilities = [Facility("a", "Pending Site", "Dhaka", Decimal("1000"), Decimal("0"), False, ["RECYCLING"], "available")]
    _, candidates = eligible(
        facilities, "RECYCLABLE", RiskLevel.LOW, SuggestedHandling.RECYCLE, Decimal("10")
    )
    assert candidates == []


def test_unavailable_facility_is_rejected():
    facilities = [Facility("a", "Offline Site", "Dhaka", Decimal("1000"), Decimal("0"), True, ["RECYCLING"], "unavailable")]
    _, candidates = eligible(
        facilities, "RECYCLABLE", RiskLevel.LOW, SuggestedHandling.RECYCLE, Decimal("10")
    )
    assert candidates == []
