"""Process configuration loaded from the environment / .env file.

Secrets (key id, private key path) live only here and inside the Kalshi client. They are
never serialized into API responses, logs, the evidence database, or exports.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Static settings read once at startup. Runtime-tunable values live in the DB."""

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    kalshi_key_id: SecretStr | None = None
    kalshi_private_key: SecretStr | None = None
    kalshi_private_key_path: Path | None = None

    specs_dir: Path = ROOT_DIR / "specs"
    data_dir: Path = ROOT_DIR / "data"
    notes_file: Path = ROOT_DIR / "notes" / "answers.json"

    request_timeout_s: float = 15.0
    max_transport_retries: int = 2

    default_rate_limit_rps: float = 2.0
    default_rate_limit_burst: int = 2
    default_max_requests_per_job: int = 50
    default_auth_check_path: str = "/portfolio/balance"

    @property
    def db_path(self) -> Path:
        """SQLite database file."""
        return self.data_dir / "kalshi_recon.db"

    @property
    def raw_dir(self) -> Path:
        """Directory holding full response bodies for reproducible charts."""
        return self.data_dir / "raw"

    @property
    def exports_dir(self) -> Path:
        """Directory for generated evidence exports."""
        return self.data_dir / "exports"

    @property
    def resolved_private_key_path(self) -> Path | None:
        """Private key path, resolving relative paths against the repo root."""
        if self.kalshi_private_key_path is None:
            return None
        path = self.kalshi_private_key_path.expanduser()
        return path if path.is_absolute() else ROOT_DIR / path

    def private_key_text(self) -> str | None:
        """Private key text: inline KALSHI_PRIVATE_KEY wins, else the KALSHI_PRIVATE_KEY_PATH file."""
        if self.kalshi_private_key is not None and self.kalshi_private_key.get_secret_value().strip():
            return self.kalshi_private_key.get_secret_value()
        key_path = self.resolved_private_key_path
        if key_path is not None and key_path.is_file():
            return key_path.read_text(encoding="utf-8")
        return None

    @property
    def credentials_configured(self) -> bool:
        """True when a key id and a private key (inline or file) are configured."""
        has_id = self.kalshi_key_id is not None and bool(self.kalshi_key_id.get_secret_value())
        return has_id and self.private_key_text() is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process settings."""
    settings = Settings()
    for directory in (settings.data_dir, settings.raw_dir, settings.exports_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return settings
