from types import SimpleNamespace
from datetime import datetime, timezone

from app.services.local_ai_service import LocalAIService


def test_trend_prediction_is_deterministic():
    service = LocalAIService.__new__(LocalAIService)
    record = SimpleNamespace(id="current", hospital_id="hospital")
    items = [
        SimpleNamespace(
            id=str(i),
            generated_at=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
            quantity=q,
            category_id="cat",
        )
        for i, q in enumerate([10, 20, 30])
    ]
    service.records = SimpleNamespace(list_for_hospital=lambda **_: items)
    result = service._trend(record)
    assert result["status"] == "completed"
    assert result["direction"] == "rising"
    assert result["next_period_quantity"] == 40.0


def test_anomaly_detection_requires_history():
    service = LocalAIService.__new__(LocalAIService)
    record = SimpleNamespace(id="current", hospital_id="hospital", category_id="cat", quantity=100)
    items = [
        SimpleNamespace(id="1", quantity=20, category_id="cat"),
        SimpleNamespace(id="2", quantity=22, category_id="cat"),
    ]
    service.records = SimpleNamespace(list_for_hospital=lambda **_: items)
    result = service._anomaly(record)
    assert result["status"] == "insufficient_history"
    assert result["is_anomaly"] is False
