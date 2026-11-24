"""Process-wide service container, built once in the FastAPI lifespan."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.config import Settings
from app.db import Database
from app.evidence import EvidenceLog
from app.jobs import JobManager
from app.kalshi_client import KalshiClient, TokenBucket
from app.settings_store import RuntimeSettings, SettingsStore
from app.spec_loader import AsyncApiSpec, OpenApiSpec


@dataclass
class Services:
    """Every long-lived dependency the API routes need."""

    config: Settings
    db: Database
    spec: OpenApiSpec
    asyncspec: AsyncApiSpec
    settings: SettingsStore
    evidence: EvidenceLog
    jobs: JobManager
    bucket: TokenBucket
    client: KalshiClient

    @classmethod
    def build(cls, config: Settings) -> Services:
        """Wire up all services from static configuration."""
        db = Database(config.db_path)
        spec = OpenApiSpec.load(config.specs_dir / "openapi.yaml")
        asyncspec = AsyncApiSpec.load(config.specs_dir / "asyncapi.yaml")
        settings = SettingsStore(db, config, spec)
        secrets = [config.kalshi_key_id.get_secret_value()] if config.kalshi_key_id else []
        evidence = EvidenceLog(db, config.raw_dir, secrets)
        jobs = JobManager(db, secrets)
        current = settings.get()
        bucket = TokenBucket(current.rate_limit_rps, current.rate_limit_burst)

        def _reconfigure(updated: RuntimeSettings) -> None:
            bucket.configure(updated.rate_limit_rps, updated.rate_limit_burst)

        settings.on_change(_reconfigure)
        client = KalshiClient(config, spec, settings, evidence, jobs, bucket)
        return cls(config, db, spec, asyncspec, settings, evidence, jobs, bucket, client)


def get_services(request: Request) -> Services:
    """FastAPI dependency returning the container stored on app.state."""
    services: Services = request.app.state.services
    return services
