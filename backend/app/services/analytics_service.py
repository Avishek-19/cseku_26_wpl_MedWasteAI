from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.hospital_profile import HospitalProfile
from app.models.incident import Incident
from app.models.matching_record import MatchingRecord
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.roles import UserRole
from app.models.user import User
from app.models.waste_classification import WasteClassification
from app.models.waste_enums import RiskLevel, WasteStatus
from app.models.waste_record import WasteRecord
from app.models.waste_risk_assessment import WasteRiskAssessment
from app.models.facility_profile import TreatmentFacilityProfile
from app.services.organization_eligibility import profile_for_user, can_profile_action

LB_TO_KG = Decimal("0.45359237")


class AnalyticsService:
    """Read-only analytics built from existing Phase 4–12 domain data.

    No new analytics table is required: metrics are derived from the current
    operational records so the dashboard cannot drift away from source data.
    """

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _kg(quantity: Decimal | float | None, unit: str) -> Decimal:
        if quantity is None:
            return Decimal("0")
        q = Decimal(str(quantity))
        if unit == "kg":
            return q
        if unit == "lb":
            return q * LB_TO_KG
        # Litres and pieces cannot be scientifically converted to mass without
        # material-specific density/weight data, so they are excluded from
        # weight-based environmental indicators rather than guessed.
        return Decimal("0")

    @staticmethod
    def _period_bounds(period: str) -> tuple[datetime, datetime]:
        now = datetime.now(timezone.utc)
        periods = {"7d": 7, "30d": 30, "90d": 90, "12m": 365}
        days = periods.get(period, 30)
        return now - timedelta(days=days), now

    def _waste_for_user(self, user: User, start: datetime, end: datetime) -> list[WasteRecord]:
        base = (
            select(WasteRecord)
            .where(WasteRecord.generated_at >= start, WasteRecord.generated_at <= end)
            .order_by(WasteRecord.generated_at.asc())
        )

        if user.role == UserRole.HOSPITAL:
            profile = profile_for_user(self.db, user.id, "HOSPITAL")
            if not profile or not can_profile_action(self.db, profile, user.id, "HOSPITAL" if user.role == UserRole.HOSPITAL else "TREATMENT_FACILITY", "waste_read" if user.role == UserRole.HOSPITAL else "facility_receive"):
                return []
            return list(self.db.execute(base.where(WasteRecord.hospital_id == profile.id)).scalars().all())

        if user.role == UserRole.FACILITY:
            profile = profile_for_user(self.db, user.id, "TREATMENT_FACILITY")
            if not profile or not can_profile_action(self.db, profile, user.id, "HOSPITAL" if user.role == UserRole.HOSPITAL else "TREATMENT_FACILITY", "waste_read" if user.role == UserRole.HOSPITAL else "facility_receive"):
                return []
            stmt = (
                base.join(MatchingRecord, MatchingRecord.waste_record_id == WasteRecord.id)
                .where(MatchingRecord.confirmed_facility_id == profile.id)
                .distinct()
            )
            return list(self.db.execute(stmt).scalars().all())

        if user.role == UserRole.COLLECTOR:
            stmt = (
                select(WasteRecord)
                .join(PickupRequestItem, PickupRequestItem.waste_record_id == WasteRecord.id)
                .join(PickupRequest, PickupRequest.id == PickupRequestItem.pickup_request_id)
                .where(
                    PickupRequest.assigned_collector_id == user.id,
                    WasteRecord.generated_at >= start,
                    WasteRecord.generated_at <= end,
                )
                .order_by(WasteRecord.generated_at.asc())
                .distinct()
            )
            return list(self.db.execute(stmt).scalars().all())

        if user.role == UserRole.ADMIN:
            return list(self.db.execute(base).scalars().all())

        return []

    def build(self, user: User, period: str = "30d") -> dict:
        start, end = self._period_bounds(period)
        records = self._waste_for_user(user, start, end)
        ids = [r.id for r in records]

        classifications = {}
        if ids:
            rows = self.db.execute(
                select(WasteClassification)
                .where(WasteClassification.waste_record_id.in_(ids))
                .order_by(WasteClassification.created_at.desc())
            ).scalars().all()
            for row in rows:
                classifications.setdefault(row.waste_record_id, row)

        risks = {}
        if ids:
            rows = self.db.execute(
                select(WasteRiskAssessment)
                .where(WasteRiskAssessment.waste_record_id.in_(ids))
                .order_by(WasteRiskAssessment.created_at.desc())
            ).scalars().all()
            for row in rows:
                risks.setdefault(row.waste_record_id, row)

        summary = {
            "total_batches": len(records),
            "tracked_weight_kg": Decimal("0"),
            "recyclable_weight_kg": Decimal("0"),
            "recycled_weight_kg": Decimal("0"),
            "treated_weight_kg": Decimal("0"),
            "disposed_weight_kg": Decimal("0"),
            "recycling_rate": 0.0,
            "high_risk_batches": 0,
            "active_batches": 0,
            "completed_batches": 0,
        }

        categories: dict[str, dict[str, float | int]] = defaultdict(lambda: {"batches": 0, "weight_kg": 0.0})
        trend: dict[str, float] = defaultdict(float)
        processing = {"recycled": 0.0, "treated": 0.0, "disposed": 0.0}

        for record in records:
            kg = self._kg(record.quantity, record.unit.value)
            summary["tracked_weight_kg"] += kg
            cat = record.category.name if record.category else "Uncategorized"
            categories[cat]["batches"] += 1
            categories[cat]["weight_kg"] += float(kg)

            if period == "7d":
                key = record.generated_at.astimezone(timezone.utc).strftime("%a")
            elif period in {"30d", "90d"}:
                key = record.generated_at.astimezone(timezone.utc).strftime("%d %b")
            else:
                key = record.generated_at.astimezone(timezone.utc).strftime("%b %Y")
            trend[key] += float(kg)

            risk = risks.get(record.id)
            if risk and risk.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
                summary["high_risk_batches"] += 1

            if record.status in {
                WasteStatus.PICKUP_REQUESTED, WasteStatus.PICKUP_ASSIGNED,
                WasteStatus.COLLECTED, WasteStatus.IN_TRANSIT,
                WasteStatus.DESTINATION_RECEIVED, WasteStatus.PROCESSING,
            }:
                summary["active_batches"] += 1
            if record.status == WasteStatus.COMPLETED:
                summary["completed_batches"] += 1

            if record.category and record.category.is_recyclable:
                summary["recyclable_weight_kg"] += kg
            if record.status == WasteStatus.RECYCLED:
                summary["recycled_weight_kg"] += kg
                processing["recycled"] += float(kg)
            elif record.status == WasteStatus.TREATED:
                summary["treated_weight_kg"] += kg
                processing["treated"] += float(kg)
            elif record.status == WasteStatus.DISPOSED:
                summary["disposed_weight_kg"] += kg
                processing["disposed"] += float(kg)

        if summary["recyclable_weight_kg"] > 0:
            summary["recycling_rate"] = round(
                float(summary["recycled_weight_kg"] / summary["recyclable_weight_kg"] * 100), 1
            )

        total_cat_batches = max(len(records), 1)
        category_distribution = [
            {
                "name": name,
                "batches": int(data["batches"]),
                "weight_kg": round(float(data["weight_kg"]), 2),
                "percentage": round(int(data["batches"]) / total_cat_batches * 100, 1),
            }
            for name, data in sorted(categories.items(), key=lambda item: (-int(item[1]["batches"]), item[0]))
        ]

        # Trend keys are already chronologically ordered because records are
        # read in generated_at order and dict insertion order is preserved.
        waste_trend = [{"label": key, "value": round(value, 2)} for key, value in trend.items()]

        notes = [
            "Weight-based environmental indicators include kg and lb records only; litres and pieces are not converted to mass.",
            "Recycling rate is calculated against recyclable-category tracked weight in the selected period.",
        ]
        if user.role == UserRole.ADMIN:
            notes.append("Platform-wide analytics are introduced with the Admin Panel in Phase 14.")
        if not records:
            notes.append("No waste records were found for the selected period and your current role scope.")

        return {
            "scope": user.role.value,
            "period": period if period in {"7d", "30d", "90d", "12m"} else "30d",
            "from_date": start,
            "to_date": end,
            "summary": summary,
            "waste_trend": waste_trend,
            "category_distribution": category_distribution,
            "processing": [
                {"label": "Recycled", "value": round(processing["recycled"], 2)},
                {"label": "Treated", "value": round(processing["treated"], 2)},
                {"label": "Disposed", "value": round(processing["disposed"], 2)},
            ],
            "notes": notes,
            "generated_at": datetime.now(timezone.utc),
        }
