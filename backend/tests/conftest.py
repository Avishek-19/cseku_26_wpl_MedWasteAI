import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from alembic.config import Config
from alembic import command
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import Base, get_db
from app.main import app
from app.core.middleware import DemoAuthRateLimitMiddleware
from app import models  # noqa: F401 — ensures all models are registered on Base.metadata
from app.models.waste_category import WasteCategory
from app.models.risk_rule import RiskRule
from app.models.waste_enums import RiskLevel

settings = get_settings()

# Run tests against a dedicated database so they never touch dev data.
TEST_DATABASE_URL = os.environ.get('TEST_DATABASE_URL') or make_url(settings.database_url).set(database='medwaste_ai_test').render_as_string(hide_password=False)
if not (make_url(TEST_DATABASE_URL).database or '').endswith('_test'):
    raise RuntimeError('TEST_DATABASE_URL must name a dedicated database ending in _test')
if make_url(TEST_DATABASE_URL) == make_url(settings.database_url):
    raise RuntimeError('Integration tests must never use the application database')

test_engine = create_engine(TEST_DATABASE_URL, future=True)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine, future=True)

_SEED_CATEGORIES = [
    ("GENERAL", "General Waste", False),
    ("INFECTIOUS", "Infectious Waste", False),
    ("SHARPS", "Sharps", False),
    ("PHARMACEUTICAL", "Pharmaceutical Waste", False),
    ("CHEMICAL", "Chemical Waste", False),
    ("PATHOLOGICAL", "Pathological Waste", False),
    ("RECYCLABLE", "Recyclable Medical Waste", True),
    ("OTHER_REGULATED", "Other Regulated Waste", False),
]

_SEED_RISK_RULES = {
    "GENERAL": (RiskLevel.LOW, None),
    "INFECTIOUS": (RiskLevel.HIGH, 50),
    "SHARPS": (RiskLevel.HIGH, 20),
    "PHARMACEUTICAL": (RiskLevel.MEDIUM, 30),
    "CHEMICAL": (RiskLevel.HIGH, 20),
    "PATHOLOGICAL": (RiskLevel.CRITICAL, None),
    "RECYCLABLE": (RiskLevel.LOW, None),
    "OTHER_REGULATED": (RiskLevel.MEDIUM, 40),
}


@pytest.fixture(scope="session", autouse=True)
def _setup_test_database():
    # Exercise the actual migration chain, sequence and seeded reference data.
    config = Config('alembic.ini')
    config.attributes['database_url'] = TEST_DATABASE_URL
    command.upgrade(config, 'head')
    with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name not in ('waste_categories', 'risk_rules'):
                conn.execute(table.delete())
    yield
    test_engine.dispose()



@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in ("waste_categories", "risk_rules"):
                continue  # seed/reference data — persists across tests
            conn.execute(table.delete())


def _override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture
def client():
    return TestClient(app, base_url="http://localhost")


@pytest.fixture(autouse=True)
def _isolate_auth_rate_limits():
    """The integration suite reuses one global FastAPI app, so its *live*
    middleware instance must be reset between tests as well.

    App-per-test unit tests require no reset: each instance has its own state.
    This fixture changes test state only; production keeps normal throttling.
    """
    layer = app.middleware_stack
    while layer is not None:
        if isinstance(layer, DemoAuthRateLimitMiddleware):
            with layer._lock:
                layer._entries.clear()
            break
        layer = getattr(layer, "app", None)
    yield


@pytest.fixture
def operation(monkeypatch):
    from tests.workflow_support import make_operation
    value = make_operation(monkeypatch)
    try:
        yield value
    finally:
        for name in ('hospital', 'collector', 'facility', 'admin'):
            getattr(value, name).close()
