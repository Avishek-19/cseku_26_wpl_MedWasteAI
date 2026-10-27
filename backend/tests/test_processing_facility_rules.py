from decimal import Decimal
from types import SimpleNamespace

from app.models.waste_enums import RiskLevel, SuggestedHandling
from app.rules.matching_rules import filter_by_capacity, rank_candidates
from app.rules.processing_rules import required_processing


def test_required_processing_for_infectious_waste():
    method, acceptable = required_processing(
        category_code="INFECTIOUS", risk_level=RiskLevel.HIGH, handling=SuggestedHandling.TREAT
    )
    assert method == "SPECIALIZED_TREATMENT"
    assert "AUTOCLAVE" in acceptable
    assert "INCINERATION" in acceptable


def test_recyclable_waste_requires_recycling():
    method, acceptable = required_processing(
        category_code="RECYCLABLE", risk_level=RiskLevel.LOW, handling=SuggestedHandling.RECYCLE
    )
    assert method == "RECYCLING"
    assert "MATERIAL_RECOVERY" in acceptable


def test_incompatible_capacity_is_hard_filtered():
    good = SimpleNamespace(id="a", name="A", city="Dhaka", capacity_kg=Decimal("500"), current_utilization_kg=Decimal("100"), is_verified=True, processing_services=["AUTOCLAVE"], availability_status="available")
    full = SimpleNamespace(id="b", name="B", city="Dhaka", capacity_kg=Decimal("100"), current_utilization_kg=Decimal("90"), is_verified=True, processing_services=["AUTOCLAVE"], availability_status="available")
    eligible = filter_by_capacity(candidates=[good, full], quantity=Decimal("50"))
    assert eligible == [good]


def test_matching_ranks_verified_processing_facility():
    candidate = SimpleNamespace(id="a", name="A", city="Dhaka", capacity_kg=Decimal("500"), current_utilization_kg=Decimal("100"), is_verified=True, processing_services=["AUTOCLAVE"], availability_status="available")
    result = rank_candidates(candidates=[candidate], quantity=Decimal("50"), hospital_city="Dhaka", hospital_region="Dhaka", high_risk=True, required_processing="AUTOCLAVE")
    assert result[0].candidate.id == "a"
    assert result[0].score <= 100
    assert any("AUTOCLAVE" in reason for reason in result[0].reasons)
