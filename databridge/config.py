"""Application settings, read from environment variables prefixed DATABRIDGE_ or a .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATABRIDGE_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    # SQLAlchemy URL for the metadata store. Blank = SQLite file inside data_dir.
    database_url: str = ""
    # Fernet key used to encrypt connection secrets. Blank = generated into data_dir/secret.key.
    secret_key: str = ""
    max_upload_mb: int = 100
    preview_rows: int = 20
    default_page_size: int = 100
    max_page_size: int = 10_000
    public_base_url: str = "http://localhost:8000"
    # Serve Flutter/CanvasKit assets locally instead of from a CDN (air-gapped or proxied networks).
    no_cdn: bool = False

    # Authentication
    session_hours: int = 12            # absolute lifetime of a normal sign-in
    remember_days: int = 14            # lifetime when "keep me signed in" is ticked
    idle_minutes: int = 60             # normal sessions end after this much inactivity
    max_failed_logins: int = 5         # then the account locks for lockout_minutes
    lockout_minutes: int = 15
    min_password_length: int = 10
    # First admin, created at startup only if there are no users yet (must change password on first sign-in).
    admin_username: str = ""
    admin_password: str = ""

    # AI
    ai_enabled: bool = True
    ai_request_timeout: int = 120          # seconds per model call
    ai_monthly_token_limit: int = 0        # per user, prompt + completion tokens; 0 = unlimited
    ai_log_content: bool = False           # store prompt/response text in the usage ledger
    # Personal API keys may only call public HTTPS endpoints (blocks SSRF into the server's network).
    ai_allow_private_urls: bool = False
    # Extra CA bundle (PEM file path) trusted for all AI calls, e.g. a company root CA or TLS-inspecting proxy.
    ai_ca_bundle: str = ""
    # Company LLM configuration file (YAML), applied at startup: endpoints, model catalog, defaults.
    ai_config_file: str = ""
    # Health checks of model endpoints: every N minutes (0 = off); alerts go to the audit log and this webhook
    # (Slack / Teams / any URL accepting {"text": ...}).
    ai_health_minutes: int = 15
    ai_alert_webhook: str = ""
    ai_cert_warn_days: int = 14

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'databridge.db').resolve()}"

    def ensure_dirs(self) -> None:
        for sub in ("snapshots", "datasets", "uploads", "rejects"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)


settings = Settings()
