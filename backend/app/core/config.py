from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator


class Settings(BaseSettings):
    """Application configuration.

    All values are loaded from environment variables / a local .env file.
    Nothing here requires a paid external service.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MedWaste AI API"
    environment: str = "development"
    debug: bool = True
    trusted_hosts: str = "localhost,127.0.0.1"
    max_request_body_bytes: int = 11 * 1024 * 1024

    # Comma-separated origins, parsed into a list below
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    database_url: str = (
        "postgresql+psycopg2://medwaste:medwaste_dev_pw@localhost:5432/medwaste_ai"
    )

    database_pool_size: int = 5
    database_max_overflow: int = 10

    local_storage_dir: str = "./storage"

    # --- Local AI (Phase 12) ---
    # Ollama is optional. The platform remains functional with deterministic
    # local fallbacks when a local model is unavailable.
    local_ai_enabled: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_text_model: str = "llama3.2:1b"
    ollama_vision_model: str = "qwen2.5vl:3b"
    ollama_timeout_seconds: float = 30.0

    # --- Hosted payments (not merchant-ready until approved onboarding) ---
    payment_mode: str = 'disabled'
    payment_public_base_url: str = 'http://localhost:8000'
    frontend_public_base_url: str = 'http://localhost:3000'
    payment_contact_phone: str = ''
    payment_live_approved: bool = False
    sslcz_store_id: str = ''
    sslcz_store_password: str = ''

    # --- Auth ---
    # Dev-only default. Every real deployment MUST override this via .env.
    jwt_secret_key: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours, revisited in Phase 15
    auth_cookie_name: str = "mw_session"
    # Cookies only travel over HTTPS when this is true — keep false for local http dev.
    auth_cookie_secure: bool = False

    # --- Real-time transport tracking (Phase 2 foundation) ---
    tracking_mode: str = "real"
    # Local development simulation: never evidence of physical pickup/delivery.
    enable_demo_manual_workflow: bool = False
    # Each trusted GPS device is explicitly enrolled by the backend operator.
    # JSON map: {"device-uuid": {"vehicle_id":"uuid", "secret_hex":"64+ hex chars"}}
    # Unenrolled telemetry is visible on the map, but NEVER certifies an arrival.
    gps_trusted_devices_json: str = "{}"
    # Redis fan-out is optional for ONE process; it is required when >1 worker.
    tracking_redis_url: str = ""
    tracking_redis_channel: str = "medwaste:tracking:events:v1"
    tracking_worker_count: int = 1
    websocket_enabled: bool = True
    gps_update_interval_seconds: int = 5
    gps_stale_threshold_seconds: int = 30
    gps_max_speed_kmh: float = 120.0
    gps_max_jump_km: float = 5.0
    websocket_heartbeat_seconds: int = 20
    route_max_duration_minutes: int = 240
    route_stop_arrival_radius_km: float = 0.2
    # --- Route optimization (Phase 3) ---
    routing_provider: str = "auto"
    routing_base_url: str = "https://router.project-osrm.org"
    routing_timeout_seconds: float = 8.0
    routing_average_speed_kmh: float = 35.0
    route_max_stops: int = 50
    pickup_business_open_hour: int = 9
    pickup_business_close_hour: int = 17
    pickup_closed_weekdays: str = "4"  # Friday in Python date.weekday(); configurable
    pickup_holidays_bd: str = ""  # Verified YYYY-MM-DD dates, comma-separated

    @model_validator(mode="after")
    def production_guardrails(self):
        if not self.gps_trusted_devices_json.strip():
            self.gps_trusted_devices_json = "{}"
        if self.payment_mode not in {"disabled", "mock", "sandbox", "live"}:
            raise ValueError("Invalid PAYMENT_MODE")
        if self.payment_mode == "mock" and self.environment.lower() != "test":
            raise ValueError("Mock payments are restricted to automated tests")
        if self.environment.lower() == "demo":
            raise ValueError("Demo deployments are not supported")
        if self.enable_demo_manual_workflow and self.environment.lower() not in {"development", "test"}:
            raise ValueError("ENABLE_DEMO_MANUAL_WORKFLOW is permitted only in development/test")
        if self.tracking_mode not in {"real", "simulation"}:
            raise ValueError("TRACKING_MODE must be real or simulation")
        if self.environment.lower() in {"production", "prod", "demo"}:
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if self.jwt_secret_key == "dev-only-insecure-secret-change-me" or len(self.jwt_secret_key) < 32:
                raise ValueError("JWT_SECRET_KEY must be a strong unique value in production")
            if not self.auth_cookie_secure:
                raise ValueError("AUTH_COOKIE_SECURE must be true in production")
            if self.payment_mode not in {"live", "disabled"}:
                raise ValueError("Production payments require live mode or disabled checkout")
            if self.tracking_mode != "real":
                raise ValueError("Production requires real GPS tracking")
            if not self.frontend_public_base_url.startswith("https://"):
                raise ValueError("FRONTEND_PUBLIC_BASE_URL must use HTTPS in production")
            if self.payment_mode == "live" and (not self.payment_live_approved or not self.payment_public_base_url.startswith("https://")):
                raise ValueError("Live merchant approval and HTTPS callback URL required")
        if self.tracking_worker_count < 1:
            raise ValueError("TRACKING_WORKER_COUNT must be at least one")
        if self.tracking_worker_count > 1 and not self.tracking_redis_url:
            raise ValueError("Multi-worker tracking requires TRACKING_REDIS_URL")
        if not self.tracking_redis_channel or len(self.tracking_redis_channel) > 180:
            raise ValueError("TRACKING_REDIS_CHANNEL must identify an isolated deployment")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()