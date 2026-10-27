from dataclasses import dataclass
from decimal import Decimal

from app.models.risk_rule import RiskRule
from app.models.waste_enums import RiskLevel, SuggestedHandling

_RISK_ORDER = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]


def _escalate(level: RiskLevel) -> RiskLevel:
    idx = _RISK_ORDER.index(level)
    return _RISK_ORDER[min(idx + 1, len(_RISK_ORDER) - 1)]


@dataclass
class RiskAssessmentResult:
    risk_level: RiskLevel
    recyclability_decision: bool
    suggested_handling: SuggestedHandling
    factors: dict
    explanation: str


def assess_risk(
    *, rule: RiskRule, category_is_recyclable: bool, quantity: Decimal
) -> RiskAssessmentResult:
    """Applies the category's configured base risk level, escalating for
    quantity where a threshold is configured. Fully deterministic — the
    thresholds themselves are admin-configurable data, not hardcoded logic."""

    risk_level = rule.base_risk_level
    quantity_escalated = False

    if rule.quantity_escalation_threshold is not None and quantity > rule.quantity_escalation_threshold:
        risk_level = _escalate(risk_level)
        quantity_escalated = True

    # Recyclable only if the category is inherently recyclable AND the
    # assessed risk stays low enough to handle safely at a Waste Processing Facility.
    recyclability_decision = category_is_recyclable and risk_level in (
        RiskLevel.LOW,
        RiskLevel.MEDIUM,
    )

    if recyclability_decision:
        suggested_handling = SuggestedHandling.RECYCLE
    elif risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        suggested_handling = SuggestedHandling.TREAT
    else:
        suggested_handling = SuggestedHandling.DISPOSE

    explanation_parts = [f"Base risk for this category is {rule.base_risk_level.value}."]
    if quantity_escalated:
        explanation_parts.append(
            f"Quantity ({quantity}) exceeds the {rule.quantity_escalation_threshold} "
            "threshold, so risk was escalated one tier."
        )
    explanation_parts.append(f"Suggested handling: {suggested_handling.value}.")

    return RiskAssessmentResult(
        risk_level=risk_level,
        recyclability_decision=recyclability_decision,
        suggested_handling=suggested_handling,
        factors={
            "base_risk_level": rule.base_risk_level.value,
            "quantity_escalated": quantity_escalated,
            "category_recyclable": category_is_recyclable,
        },
        explanation=" ".join(explanation_parts),
    )
