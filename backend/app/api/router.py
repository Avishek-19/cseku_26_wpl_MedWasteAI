from fastapi import APIRouter

from app.api import (
    auth,
    business,
    workflow,
    payments,
    analytics,
    admin,
    destinations,
    facilities,
    health,
    hospitals,
    matching,
    notifications,
    local_ai,
    tracking,
    tracking_simulator,
    routes,
    pickups,
    processing,
    risk_assessment,
    vehicles,
    waste,
    waste_classification,
    waste_timeline,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(analytics.router)
api_router.include_router(admin.router)
api_router.include_router(hospitals.router)
api_router.include_router(waste.router)
api_router.include_router(waste_classification.router)
api_router.include_router(risk_assessment.router)
api_router.include_router(vehicles.router)
api_router.include_router(pickups.router)
api_router.include_router(processing.router)
api_router.include_router(facilities.router)
api_router.include_router(matching.router)
api_router.include_router(waste_timeline.router)
api_router.include_router(destinations.router)
api_router.include_router(notifications.router)
api_router.include_router(local_ai.router)
api_router.include_router(tracking.router)
# Simulation utilities remain available to isolated tests, never public routes.
api_router.include_router(routes.router)

api_router.include_router(business.router)
api_router.include_router(payments.router)

api_router.include_router(workflow.router)

from app.api import manual_workflow

api_router.include_router(manual_workflow.router)
