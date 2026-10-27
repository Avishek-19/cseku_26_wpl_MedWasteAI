from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class MatchCandidate(Protocol):
    id: object
    name: str
    city: str
    capacity_kg: Decimal
    current_utilization_kg: Decimal
    is_verified: bool
    processing_services: list
    availability_status: str


@dataclass
class ScoredCandidate:
    candidate: MatchCandidate
    score: int
    reasons: list[str]


MAX_CANDIDATES_RETURNED = 5


def _capacity_headroom(candidate: MatchCandidate) -> Decimal:
    return Decimal(str(candidate.capacity_kg)) - Decimal(str(candidate.current_utilization_kg))


def score_candidate(
    *, candidate: MatchCandidate, quantity: Decimal, hospital_city: str, hospital_region: str, high_risk: bool, required_processing: str | None = None
) -> ScoredCandidate:
    reasons: list[str] = []
    score = 0

    # Required processing is a hard filter before scoring.
    if required_processing and required_processing in [str(x).upper() for x in getattr(candidate, "processing_services", [])]:
        score += 5
        reasons.append(f"Provides {required_processing} (+5)")

    # Verification — up to 35 points. Not a hard filter (no admin
    # verification workflow exists until Phase 14), but heavily weighted.
    if candidate.is_verified:
        score += 35
        reasons.append("Verified (+35)")
    else:
        reasons.append("Not yet verified (+0)")

    # Capacity headroom — up to 30 points, scaled by how much spare room
    # remains after this batch, so a nearly-full site scores lower.
    headroom_after = _capacity_headroom(candidate) - quantity
    headroom_ratio = float(headroom_after / Decimal(str(candidate.capacity_kg))) if candidate.capacity_kg else 0
    headroom_points = max(0, min(30, round(headroom_ratio * 30)))
    score += headroom_points
    reasons.append(f"Capacity headroom after this batch (+{headroom_points})")

    # Availability — up to 5 points (unavailable is already a hard filter).
    if getattr(candidate, "availability_status", "available") == "available":
        score += 5
        reasons.append("Currently available (+5)")
    else:
        score += 2
        reasons.append("Limited availability (+2)")

    # Location — up to 20 points. No maps/geocoding (spec constraint); city
    # match is used as a simple proxy for "close by".
    if candidate.city.strip().lower() == hospital_city.strip().lower():
        score += 20
        reasons.append("Same city as hospital (+20)")
    elif hospital_region:
        score += 10
        reasons.append("Same region as hospital (+10)")

    # Risk-priority alignment — up to 5 points, only relevant (and only
    # awarded) for high/critical-risk waste being sent to a verified site.
    if high_risk and candidate.is_verified:
        score += 5
        reasons.append("Verified site for high-risk waste (+5)")

    return ScoredCandidate(candidate=candidate, score=score, reasons=reasons)


def rank_candidates(
    *,
    candidates: list[MatchCandidate],
    quantity: Decimal,
    hospital_city: str,
    hospital_region: str,
    high_risk: bool,
    required_processing: str | None = None,
) -> list[ScoredCandidate]:
    scored = [
        score_candidate(
            candidate=c,
            quantity=quantity,
            hospital_city=hospital_city,
            hospital_region=hospital_region,
            high_risk=high_risk,
            required_processing=required_processing,
        )
        for c in candidates
    ]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:MAX_CANDIDATES_RETURNED]


def filter_by_capacity(*, candidates: list[MatchCandidate], quantity: Decimal) -> list[MatchCandidate]:
    """Hard filter: only candidates with enough free capacity for the whole
    batch. Waste-category compatibility is already applied at the query
    level (only compatible candidates are fetched in the first place)."""
    return [c for c in candidates if _capacity_headroom(c) >= quantity]
