"""Environment-driven settings. Admin overrides are layered on top by config_store."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Keys an admin may override at runtime (stored in the `settings` table). Never secrets.
OVERRIDABLE: dict[str, type] = {
    "image_model": str,
    "transcribe_model": str,
    "review_model": str,
    "pixel_cap": int,
    "upstream_concurrency": int,
    "guest_daily_per_ip": int,
    "guest_daily_global": int,
    "user_daily_default": int,
    "retention_user_days": int,
    "retention_guest_hours": int,
    "max_upload_mb": int,
    "max_pixels": int,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    open_api_base_url: str = "https://your-relay.example.com"
    open_api_key: str = ""
    image_model: str = "gpt-image-2.5"
    transcribe_model: str = "gpt-6-sol"
    review_model: str = "gpt-6-sol"
    pixel_cap: int = 1_550_000
    upstream_concurrency: int = 3
    guest_daily_per_ip: int = 3
    guest_daily_global: int = 100
    user_daily_default: int = 50
    retention_user_days: int = 30
    retention_guest_hours: int = 24
    max_upload_mb: int = 15
    max_pixels: int = 25_000_000
    session_days: int = 14
    cookie_secure: bool = True
    client_ip_header: str = "X-Forwarded-For"
    trusted_proxies: str = "127.0.0.1,172.16.0.0/12"
    data_dir: Path = Path("/data")
    host_port: int = 18090
    image_timeout_s: float = 180.0
    chat_timeout_s: float = 240.0
    min_free_bytes: int = 1_000_000_000
    static_dir: Path = Path("frontend/dist")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db" / "imgsr.sqlite3"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backup"

    def with_overrides(self, overrides: dict[str, object]) -> Settings:
        clean = {k: OVERRIDABLE[k](v) for k, v in overrides.items() if k in OVERRIDABLE}
        return self.model_copy(update=clean)
