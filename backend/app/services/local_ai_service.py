import base64
import json
import statistics
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.waste_enums import RiskLevel, SuggestedHandling
from app.models.matching_record import MatchingRecord
from sqlalchemy import select
from app.repositories.waste_record_repository import WasteRecordRepository
from app.rules.classification_rules import classify
from app.rules.risk_assessment_rules import assess_risk
from app.rules.processing_rules import required_processing
from app.repositories.risk_rule_repository import RiskRuleRepository
from app.repositories.waste_category_repository import WasteCategoryRepository

settings = get_settings()


class LocalAIUnavailable(Exception):
    pass


class LocalAIService:
    """Phase 12 local intelligence layer.

    Ollama is used only when configured and reachable. Every safety-sensitive
    result is either rule-validated or explicitly marked as requiring human
    verification. No cloud AI provider is contacted.
    """

    DISCLAIMER = (
        "AI output is advisory only. It is not a medical, legal, regulatory, "
        "or safety authority. Verify safety-critical decisions with approved staff."
    )

    def __init__(self, db: Session):
        self.db = db
        self.records = WasteRecordRepository(db)
        self.categories = WasteCategoryRepository(db)
        self.risk_rules = RiskRuleRepository(db)

    def _ollama(self, *, prompt: str, model: str, image_bytes: bytes | None = None) -> str:
        if not settings.local_ai_enabled:
            raise LocalAIUnavailable("Local AI is disabled.")
        payload = {"model": model, "prompt": prompt, "stream": False}
        if image_bytes is not None:
            payload["images"] = [base64.b64encode(image_bytes).decode("ascii")]
        request = urllib.request.Request(
            settings.ollama_base_url.rstrip("/") + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.ollama_timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LocalAIUnavailable(str(exc)) from exc
        return str(body.get("response", "")).strip()

    @staticmethod
    def _safe_float(value, default=0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _classification(self, record):
        result = classify(
            description=record.description,
            reported_category_code=record.category.code,
        )
        category = self.categories.get_by_code(result.suggested_category_code)
        confidence_map = {"high": 0.92, "medium": 0.72, "low": 0.45}
        return {
            "category_code": result.suggested_category_code,
            "category_name": category.name if category else result.suggested_category_code,
            "confidence": confidence_map.get(result.confidence, 0.5),
            "reasoning": result.explanation,
            "requires_verification": True,
        }

    def _risk(self, record):
        rule = self.risk_rules.get_for_category(record.category_id)
        if rule is None:
            return {
                "risk_level": RiskLevel.MEDIUM.value,
                "suggested_handling": SuggestedHandling.DISPOSE.value,
                "confidence": 0.0,
                "reasoning": "No configured risk rule was found; human assessment is required.",
                "requires_verification": True,
            }
        result = assess_risk(
            rule=rule,
            category_is_recyclable=record.category.is_recyclable,
            quantity=record.quantity,
        )
        return {
            "risk_level": result.risk_level.value,
            "suggested_handling": result.suggested_handling.value,
            "confidence": 0.90,
            "reasoning": result.explanation,
            "requires_verification": True,
        }

    def _recyclability(self, record):
        recyclable = bool(record.category.is_recyclable)
        return {
            "recyclable": recyclable,
            "confidence": 0.90 if recyclable else 0.88,
            "reasoning": (
                f"Category '{record.category.name}' is configured as "
                f"{'recyclable' if recyclable else 'not recyclable'} in the platform rules."
            ),
            "requires_verification": True,
        }

    def _image(self, record):
        image = next(
            (a for a in record.attachments if a.content_type.startswith("image/")),
            None,
        )
        if image is None:
            return {
                "status": "no_image",
                "model": None,
                "observations": "No image attachment is available for visual analysis.",
                "suggested_category": None,
                "confidence": None,
                "requires_verification": True,
            }
        path = Path(settings.local_storage_dir) / image.storage_path
        if not path.exists():
            return {
                "status": "missing_file",
                "model": None,
                "observations": "The image attachment is missing from local storage.",
                "suggested_category": None,
                "confidence": None,
                "requires_verification": True,
            }
        prompt = (
            "You are assisting medical-waste staff. Inspect this image conservatively. "
            "Describe visible waste characteristics only; do not claim certainty. "
            "Return concise observations and, if justified, a possible waste category. "
            "Never state that an image alone proves safe handling."
        )
        try:
            text = self._ollama(
                prompt=prompt,
                model=settings.ollama_vision_model,
                image_bytes=path.read_bytes(),
            )
            return {
                "status": "completed",
                "model": settings.ollama_vision_model,
                "observations": text or "The local vision model returned no observations.",
                "suggested_category": None,
                "confidence": None,
                "requires_verification": True,
            }
        except LocalAIUnavailable:
            return {
                "status": "model_unavailable",
                "model": settings.ollama_vision_model,
                "observations": (
                    "A local vision model is configured but unavailable. Start Ollama "
                    "and install the configured vision model to enable image analysis."
                ),
                "suggested_category": None,
                "confidence": None,
                "requires_verification": True,
            }

    def _anomaly(self, record):
        history = self.records.list_for_hospital(hospital_id=record.hospital_id, limit=200)
        values = [
            self._safe_float(r.quantity)
            for r in history
            if r.id != record.id and r.category_id == record.category_id
        ]
        current = self._safe_float(record.quantity)
        if len(values) < 3:
            return {
                "status": "insufficient_history",
                "is_anomaly": False,
                "score": 0.0,
                "baseline_mean": statistics.mean(values) if values else None,
                "baseline_median": statistics.median(values) if values else None,
                "message": "At least three comparable historical records are needed for anomaly scoring.",
                "requires_verification": True,
            }
        median = statistics.median(values)
        deviations = [abs(v - median) for v in values]
        mad = statistics.median(deviations)
        if mad > 0:
            score = abs(current - median) / (1.4826 * mad)
        else:
            mean = statistics.mean(values)
            std = statistics.pstdev(values)
            score = abs(current - mean) / std if std > 0 else (1.0 if current != mean else 0.0)
        is_anomaly = score >= 3.0
        return {
            "status": "completed",
            "is_anomaly": is_anomaly,
            "score": round(score, 2),
            "baseline_mean": round(statistics.mean(values), 2),
            "baseline_median": round(median, 2),
            "message": (
                "Quantity is unusually far from the historical category baseline."
                if is_anomaly
                else "No strong quantity anomaly detected against the historical baseline."
            ),
            "requires_verification": True,
        }

    def _trend(self, record):
        history = self.records.list_for_hospital(hospital_id=record.hospital_id, limit=200)
        buckets = defaultdict(float)
        for item in history:
            day = item.generated_at.date().isoformat()
            buckets[day] += self._safe_float(item.quantity)
        points = [{"period": k, "quantity": round(v, 2)} for k, v in sorted(buckets.items())]
        if len(points) < 2:
            return {
                "status": "insufficient_history",
                "method": "linear_regression",
                "direction": "insufficient_data",
                "next_period_quantity": None,
                "points": points,
                "message": "At least two historical periods are needed for a trend estimate.",
                "is_estimate": True,
            }
        ys = [p["quantity"] for p in points]
        xs = list(range(len(ys)))
        x_mean, y_mean = statistics.mean(xs), statistics.mean(ys)
        denominator = sum((x - x_mean) ** 2 for x in xs)
        slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator if denominator else 0
        intercept = y_mean - slope * x_mean
        prediction = max(0.0, intercept + slope * len(ys))
        direction = "rising" if slope > 0.05 else "falling" if slope < -0.05 else "stable"
        return {
            "status": "completed",
            "method": "local_linear_regression",
            "direction": direction,
            "next_period_quantity": round(prediction, 2),
            "points": points,
            "message": "Estimate based on historical generated quantities; it is not a scientific forecast.",
            "is_estimate": True,
        }

    def _matching(self, record):
        latest = self.db.execute(
            select(MatchingRecord)
            .where(MatchingRecord.waste_record_id == record.id)
            .order_by(MatchingRecord.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest is None:
            return {
                "status": "no_match_run",
                "recommendation": None,
                "candidates": [],
                "explanation": "Run deterministic destination matching first; local AI can assist with interpreting its ranked candidates.",
                "requires_verification": True,
            }
        candidates = latest.candidates or []
        return {
            "status": "completed",
            "recommendation": candidates[0]["name"] if candidates else None,
            "candidates": candidates[:5],
            "explanation": (
                "Recommendation assistance is grounded in the existing deterministic "
                "matching result. Compatibility, capacity, verification and availability "
                "remain authoritative filters."
            ),
            "requires_verification": True,
        }

    def analyze(self, *, user_id: uuid.UUID, record_id: uuid.UUID):
        from app.services.waste_service import WasteService
        record = WasteService(self.db).get_record(user_id=user_id, record_id=record_id)
        classification = self._classification(record)
        risk = self._risk(record)
        recyclability = self._recyclability(record)
        processing_method, acceptable_methods = required_processing(
            category_code=record.category.code,
            risk_level=RiskLevel(risk["risk_level"]),
            handling=SuggestedHandling(risk["suggested_handling"]),
        )
        processing = {
            "required_processing": processing_method,
            "acceptable_methods": acceptable_methods,
            "confidence": 0.90 if risk["confidence"] else 0.0,
            "reasoning": "Derived deterministically from the confirmed risk/handling rule and waste category.",
            "requires_verification": True,
        }
        image = self._image(record)
        anomaly = self._anomaly(record)
        trend = self._trend(record)
        matching = self._matching(record)

        # Optional local LLM interpretation: never used to bypass rule validation.
        provider = "local-rules"
        model = None
        summary = (
            f"Local rules suggest {classification['category_name']} with "
            f"{risk['risk_level']} risk and "
            f"{'potential recyclability' if recyclability['recyclable'] else 'no configured recyclability'}. "
            "Human verification is required before safety-critical action."
        )
        if settings.local_ai_enabled:
            try:
                prompt = (
                    "Summarize this advisory medical-waste assessment in two concise sentences. "
                    "Do not invent facts and explicitly say staff verification is required.\n"
                    f"Category: {classification['category_name']}\n"
                    f"Risk: {risk['risk_level']}\n"
                    f"Handling: {risk['suggested_handling']}\n"
                    f"Required processing: {processing_method}\n"
                    f"Recyclable: {recyclability['recyclable']}\n"
                    f"Anomaly: {anomaly['is_anomaly']}\n"
                    f"Trend: {trend['direction']}"
                )
                local_summary = self._ollama(prompt=prompt, model=settings.ollama_text_model)
                if local_summary:
                    summary = local_summary
                    provider = "ollama+local-rules"
                    model = settings.ollama_text_model
            except LocalAIUnavailable:
                pass

        from app.schemas.ai import AIAnalysisResponse
        return AIAnalysisResponse(
            waste_record_id=record.id,
            generated_at=datetime.now(timezone.utc),
            provider=provider,
            model=model,
            disclaimer=self.DISCLAIMER,
            summary=summary,
            classification=classification,
            risk=risk,
            recyclability=recyclability,
            processing=processing,
            image=image,
            anomaly=anomaly,
            trend=trend,
            matching=matching,
        )
