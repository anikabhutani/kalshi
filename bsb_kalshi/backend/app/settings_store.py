"""User-editable runtime settings persisted in the single-row ``settings`` table."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field

from app.config import Settings
from app.db import Database
from app.models import AppSettings
from app.spec_loader import OpenApiSpec


class RuntimeSettings(BaseModel):
    """Settings the user can change from the UI. Contains no secrets."""

    api_version: str | None = None
    date_checked: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    base_url: str
    rate_limit_rps: float = Field(gt=0, le=20)
    rate_limit_burst: int = Field(ge=1, le=50)
    max_requests_per_job: int = Field(ge=1, le=5000)
    auth_check_path: str


class SettingsPatch(BaseModel):
    """Partial update; omitted fields are unchanged."""

    api_version: str | None = None
    date_checked: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    base_url: str | None = None
    rate_limit_rps: float | None = Field(default=None, gt=0, le=20)
    rate_limit_burst: int | None = Field(default=None, ge=1, le=50)
    max_requests_per_job: int | None = Field(default=None, ge=1, le=5000)
    auth_check_path: str | None = None


class SettingsStore:
    """Reads/writes RuntimeSettings and notifies listeners (e.g. the rate limiter)."""

    def __init__(self, db: Database, config: Settings, spec: OpenApiSpec) -> None:
        self._db = db
        self._spec = spec
        self._listeners: list[Callable[[RuntimeSettings], None]] = []
        with self._db.session() as session:
            if session.get(AppSettings, 1) is None:
                session.add(
                    AppSettings(
                        id=1,
                        base_url=spec.server_urls[0],
                        rate_limit_rps=config.default_rate_limit_rps,
                        rate_limit_burst=config.default_rate_limit_burst,
                        max_requests_per_job=config.default_max_requests_per_job,
                        auth_check_path=config.default_auth_check_path,
                    )
                )
        self._cached = self._load()

    def get(self) -> RuntimeSettings:
        """Current settings (cached in memory)."""
        return self._cached

    def auth_check_choices(self) -> list[str]:
        """Spec GET endpoints that require auth and need no path or required query params."""
        return [
            e.path
            for e in self._spec.get_endpoints()
            if e.auth_required and not e.path_params and not e.required_query_params
        ]

    def update(self, patch: SettingsPatch) -> RuntimeSettings:
        """Validate and apply a partial update."""
        changes = patch.model_dump(exclude_unset=True)
        if "base_url" in changes and changes["base_url"] not in self._spec.server_urls:
            raise ValueError("base_url must be one of the servers listed in specs/openapi.yaml")
        if "auth_check_path" in changes and changes["auth_check_path"] not in (
            self.auth_check_choices()
        ):
            raise ValueError(
                "auth_check_path must be an authenticated GET endpoint from the spec "
                "without path parameters"
            )
        with self._db.session() as session:
            row = session.get(AppSettings, 1)
            assert row is not None
            for key, value in changes.items():
                setattr(row, key, value)
        self._cached = self._load()
        for listener in self._listeners:
            listener(self._cached)
        return self._cached

    def on_change(self, listener: Callable[[RuntimeSettings], None]) -> None:
        """Register a callback invoked after every successful update."""
        self._listeners.append(listener)

    def _load(self) -> RuntimeSettings:
        with self._db.session() as session:
            row = session.get(AppSettings, 1)
            assert row is not None
            return RuntimeSettings(
                api_version=row.api_version,
                date_checked=row.date_checked,
                base_url=row.base_url,
                rate_limit_rps=row.rate_limit_rps,
                rate_limit_burst=row.rate_limit_burst,
                max_requests_per_job=row.max_requests_per_job,
                auth_check_path=row.auth_check_path,
            )
