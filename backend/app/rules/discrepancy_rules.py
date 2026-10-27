from dataclasses import dataclass
from decimal import Decimal

from app.models.waste_enums import IncidentSeverity

# A discrepancy below this percentage is normal measurement variance and
# isn't flagged at all.
MINOR_THRESHOLD_PERCENT = Decimal("5")
# At or above this percentage, the discrepancy is treated as major.
MAJOR_THRESHOLD_PERCENT = Decimal("15")


@dataclass
class DiscrepancyResult:
    has_discrepancy: bool
    severity: IncidentSeverity | None
    variance_percent: Decimal
    description: str


def detect_discrepancy(*, reported_quantity: Decimal, received_quantity: Decimal) -> DiscrepancyResult:
    if reported_quantity == 0:
        variance_percent = Decimal("0")
    else:
        variance_percent = abs(reported_quantity - received_quantity) / reported_quantity * 100

    if variance_percent < MINOR_THRESHOLD_PERCENT:
        return DiscrepancyResult(
            has_discrepancy=False,
            severity=None,
            variance_percent=variance_percent,
            description="Received weight matches the reported weight within normal variance.",
        )

    severity = (
        IncidentSeverity.MAJOR if variance_percent >= MAJOR_THRESHOLD_PERCENT else IncidentSeverity.MINOR
    )
    direction = "less than" if received_quantity < reported_quantity else "more than"
    description = (
        f"Reported {reported_quantity} kg but Waste Processing Facility received {received_quantity} kg "
        f"— {round(variance_percent, 1)}% {direction} reported."
    )
    return DiscrepancyResult(
        has_discrepancy=True,
        severity=severity,
        variance_percent=variance_percent,
        description=description,
    )
