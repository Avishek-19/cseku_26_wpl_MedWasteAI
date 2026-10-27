import enum


class WasteStatus(str, enum.Enum):
    REPORTED = "reported"
    CLASSIFIED = "classified"
    RISK_ASSESSED = "risk_assessed"
    SEGREGATED = "segregated"
    PICKUP_REQUESTED = "pickup_requested"
    PICKUP_ASSIGNED = "pickup_assigned"
    COLLECTED = "collected"
    IN_TRANSIT = "in_transit"
    DESTINATION_RECEIVED = "destination_received"
    PROCESSING = "processing"
    RECYCLED = "recycled"
    TREATED = "treated"
    DISPOSED = "disposed"
    PROOF_SUBMITTED = "proof_submitted"
    VERIFIED = "verified"
    COMPLETED = "completed"


class WasteUnit(str, enum.Enum):
    KG = "kg"
    LB = "lb"
    L = "l"
    PCS = "pcs"


class ClassificationConfidence(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ClassificationSource(str, enum.Enum):
    RULE_ENGINE = "rule_engine"
    MANUAL = "manual"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SuggestedHandling(str, enum.Enum):
    RECYCLE = "recycle"
    TREAT = "treat"
    DISPOSE = "dispose"


class AssessmentSource(str, enum.Enum):
    RULE_ENGINE = "rule_engine"
    MANUAL = "manual"


class PickupPriority(str, enum.Enum):
    NORMAL = "normal"
    URGENT = "urgent"
    EMERGENCY = "emergency"


class PickupStatus(str, enum.Enum):
    REQUESTED = "requested"
    ASSIGNED = "assigned"
    COLLECTED = "collected"
    IN_TRANSIT = "in_transit"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class VehicleStatus(str, enum.Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    ON_ROUTE = "on_route"
    MAINTENANCE = "maintenance"


class DestinationType(str, enum.Enum):
    WASTE_PROCESSING_FACILITY = "waste_processing_facility"


class WasteEventType(str, enum.Enum):
    """Chain-of-custody event log (spec section 15). Extended with new
    values in later phases (transport, processing, disposal, verification)
    without needing to touch existing rows."""

    REPORTED = "reported"
    CLASSIFIED = "classified"
    RISK_ASSESSED = "risk_assessed"
    MATCHED = "matched"
    PICKUP_REQUESTED = "pickup_requested"
    PICKUP_ASSIGNED = "pickup_assigned"
    PICKUP_CANCELLED = "pickup_cancelled"
    COLLECTED = "collected"
    IN_TRANSIT = "in_transit"
    DESTINATION_RECEIVED = "destination_received"
    PROCESSING = "processing"
    PROOF_SUBMITTED = "proof_submitted"
    VERIFIED = "verified"
    COMPLETED = "completed"


class IncidentType(str, enum.Enum):
    WEIGHT_DISCREPANCY = "weight_discrepancy"


class IncidentSeverity(str, enum.Enum):
    MINOR = "minor"
    MAJOR = "major"
