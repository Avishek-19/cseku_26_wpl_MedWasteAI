from dataclasses import dataclass
from decimal import Decimal

from app.rules.matching_rules import filter_by_capacity, rank_candidates
from app.rules.processing_rules import required_processing
from app.models.waste_enums import RiskLevel, SuggestedHandling, DestinationType


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


def test_recyclable_waste_requires_recycling_capability():
    required, acceptable = required_processing(
        category_code="RECYCLABLE",
        risk_level=RiskLevel.LOW,
        handling=SuggestedHandling.RECYCLE,
    )
    assert required == "RECYCLING"
    assert "MATERIAL_RECOVERY" in acceptable


def test_infectious_waste_accepts_treatment_methods():
    required, acceptable = required_processing(
        category_code="INFECTIOUS",
        risk_level=RiskLevel.HIGH,
        handling=SuggestedHandling.TREAT,
    )
    assert required == "SPECIALIZED_TREATMENT"
    assert "AUTOCLAVE" in acceptable
    assert "INCINERATION" in acceptable


def test_capacity_filter_rejects_full_facility():
    facility = Facility("1", "Full", "Dhaka", Decimal("100"), Decimal("95"), True, ["RECYCLING"], "available")
    assert filter_by_capacity(candidates=[facility], quantity=Decimal("10")) == []


def test_unverified_facility_is_not_ranked_as_eligible_by_policy():
    facility = Facility("1", "Pending", "Dhaka", Decimal("100"), Decimal("0"), False, ["RECYCLING"], "available")
    assert facility.is_verified is False


def test_rank_prefers_verified_same_city_facility():
    local = Facility("1", "Local", "Dhaka", Decimal("1000"), Decimal("100"), True, ["RECYCLING"], "available")
    far = Facility("2", "Far", "Chattogram", Decimal("1000"), Decimal("100"), True, ["RECYCLING"], "available")
    ranked = rank_candidates(
        candidates=[far, local],
        quantity=Decimal("50"),
        hospital_city="Dhaka",
        hospital_region="Dhaka",
        high_risk=False,
        required_processing="RECYCLING",
    )
    assert ranked[0].candidate.id == "1"


def test_destination_type_is_unified():
    assert DestinationType.WASTE_PROCESSING_FACILITY.value == "waste_processing_facility"
    assert [item.value for item in DestinationType] == ["waste_processing_facility"]
