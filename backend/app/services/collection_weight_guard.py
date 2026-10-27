"""Conservative, route-wide measured-load validation at hospital handover.

Only mass quantities are supported; an unconvertible/missing batch is a hard
stop rather than a guessed kg value. Called *after locking the vehicle row* in
PickupService.collect_pickup to serialize concurrent handovers on one vehicle.
"""
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.collection_proof import CollectionProof
from app.models.pickup_request import PickupRequest
from app.models.route import RouteStop, RouteStopStatus
from app.models.waste_enums import PickupStatus
from app.rules.discrepancy_rules import DiscrepancyResult, detect_discrepancy
from app.services.quantity_service import quantity_to_kg


class CollectionWeightError(ValueError):
    """Weight evidence or the planned/measured vehicle load is unsafe."""


@dataclass(frozen=True)
class CollectionLoadCheck:
    reported_kg: Decimal
    measured_kg: Decimal
    already_collected_kg: Decimal
    remaining_reserved_kg: Decimal
    projected_load_kg: Decimal
    vehicle_capacity_kg: Decimal
    discrepancy: DiscrepancyResult


def _reported_weight(pickup: PickupRequest) -> Decimal:
    if not pickup.items:
        raise CollectionWeightError('Pickup has no waste batches; handover is blocked.')
    total = Decimal('0')
    for item in pickup.items:
        record = item.waste_record
        if record is None:
            raise CollectionWeightError('A waste batch is missing from the pickup.')
        weight = quantity_to_kg(record.quantity, record.unit)
        if weight is None or not weight.is_finite() or weight <= 0:
            raise CollectionWeightError('A waste batch has no valid kg-equivalent weight; manual review required.')
        total += weight
    return total


def check_collection_load(
    db: Session, *, route_id: UUID, pickup_id: UUID,
    actual_weight_kg: Decimal, capacity_kg: Decimal,
) -> CollectionLoadCheck:
    """Fail closed if current load + reserved pending load exceeds capacity.

    Includes actual mass from every previously collected stop, not its report.
    Pending stops keep their originally reserved mass. Cancelled/skipped stops
    are excluded. The caller must hold a FOR UPDATE lock on the vehicle to
    serialize proof creation and this calculation for concurrent collectors.
    """
    if not actual_weight_kg.is_finite() or actual_weight_kg <= 0:
        raise CollectionWeightError('Measured weight must be a finite positive amount.')
    if not capacity_kg.is_finite() or capacity_kg <= 0:
        raise CollectionWeightError('Vehicle has no valid positive weight capacity.')

    stops = db.scalars(select(RouteStop).where(RouteStop.route_id == route_id).order_by(RouteStop.sequence)).all()
    if not stops:
        raise CollectionWeightError('Active route contains no stops.')
    ids = [stop.pickup_id for stop in stops if stop.status not in {RouteStopStatus.CANCELLED, RouteStopStatus.SKIPPED}]
    pickups = {p.id: p for p in db.scalars(select(PickupRequest).where(PickupRequest.id.in_(ids))).all()}
    proofs = {proof.pickup_id: proof for proof in db.scalars(
        select(CollectionProof).where(CollectionProof.pickup_id.in_(ids))
    ).all()}

    already_collected = Decimal('0')
    remaining_reserved = Decimal('0')
    current_reported = None
    for stop in stops:
        if stop.status in {RouteStopStatus.CANCELLED, RouteStopStatus.SKIPPED}:
            continue
        pickup = pickups.get(stop.pickup_id)
        if pickup is None:
            raise CollectionWeightError('A route pickup no longer exists; re-plan or request dispatch review.')
        proof = proofs.get(pickup.id)
        if pickup.id == pickup_id:
            if stop.status != RouteStopStatus.ARRIVED or pickup.status != PickupStatus.ASSIGNED or proof is not None:
                raise CollectionWeightError('This pickup is not eligible for a new handover.')
            current_reported = _reported_weight(pickup)
            continue
        if proof is not None:
            if stop.status != RouteStopStatus.COLLECTED or pickup.status not in {
                PickupStatus.COLLECTED, PickupStatus.IN_TRANSIT, PickupStatus.COMPLETED
            }:
                raise CollectionWeightError('Prior collected pickup has inconsistent route/proof status.')
            measured = Decimal(str(proof.accepted_weight_kg))
            if not measured.is_finite() or measured <= 0:
                raise CollectionWeightError('A prior collection proof has invalid measured mass.')
            already_collected += measured
        else:
            if stop.status == RouteStopStatus.COLLECTED or pickup.status != PickupStatus.ASSIGNED:
                raise CollectionWeightError('Route load cannot be verified: previous proof or pickup state is missing.')
            remaining_reserved += _reported_weight(pickup)

    if current_reported is None:
        raise CollectionWeightError('Current pickup is not an eligible stop on the active route.')
    projected = already_collected + actual_weight_kg + remaining_reserved
    if projected > capacity_kg:
        raise CollectionWeightError(
            f'Unsafe vehicle load: {projected:.3f} kg projected '
            f'(collected {already_collected:.3f} + measured {actual_weight_kg:.3f} '
            f'+ remaining reserved {remaining_reserved:.3f}) exceeds '
            f'vehicle capacity {capacity_kg:.3f} kg. '
            'Do not load this waste; contact dispatch for a safe resolution.'
        )
    return CollectionLoadCheck(
        reported_kg=current_reported, measured_kg=actual_weight_kg,
        already_collected_kg=already_collected, remaining_reserved_kg=remaining_reserved,
        projected_load_kg=projected, vehicle_capacity_kg=capacity_kg,
        discrepancy=detect_discrepancy(reported_quantity=current_reported, received_quantity=actual_weight_kg),
    )
