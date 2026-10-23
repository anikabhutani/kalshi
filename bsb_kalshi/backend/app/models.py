"""SQLAlchemy ORM models for the evidence log, notes, settings, and jobs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all tables."""


class RequestLog(Base):
    """One row per outgoing HTTP request (including retries). Secrets are never stored."""

    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str | None] = mapped_column(String(36), index=True)
    module: Mapped[str] = mapped_column(String(16), index=True)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    method: Mapped[str] = mapped_column(String(8))
    url: Mapped[str] = mapped_column(Text)
    path_template: Mapped[str | None] = mapped_column(Text)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    auth_used: Mapped[bool] = mapped_column(Boolean)
    status_code: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    response_bytes: Mapped[int | None] = mapped_column(Integer)
    response_headers_json: Mapped[str] = mapped_column(Text, default="{}")
    response_body_sample: Mapped[str | None] = mapped_column(Text)
    raw_path: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class Note(Base):
    """User-typed findings per research question. The app never writes these."""

    __tablename__ = "notes"

    question_id: Mapped[str] = mapped_column(String(4), primary_key=True)
    text: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EndpointRating(Base):
    """User-typed usefulness rating (1-5) and reason per endpoint. Feeds Q5."""

    __tablename__ = "endpoint_ratings"

    endpoint_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    rating: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AppSettings(Base):
    """Single-row table of user-editable runtime settings."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    api_version: Mapped[str | None] = mapped_column(String(32))
    date_checked: Mapped[str | None] = mapped_column(String(10))
    base_url: Mapped[str] = mapped_column(Text)
    rate_limit_rps: Mapped[float] = mapped_column(Float)
    rate_limit_burst: Mapped[int] = mapped_column(Integer)
    max_requests_per_job: Mapped[int] = mapped_column(Integer)
    auth_check_path: Mapped[str] = mapped_column(Text)


class SportsbookDataset(Base):
    """An uploaded (or generated dummy) sportsbook odds file, parsed and validated (M7)."""

    __tablename__ = "sportsbook_datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    is_dummy: Mapped[bool] = mapped_column(Boolean, default=False)
    source_job_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rows_json: Mapped[str] = mapped_column(Text)
    errors_json: Mapped[str] = mapped_column(Text, default="[]")
    notes_json: Mapped[str] = mapped_column(Text, default="[]")
    error_count: Mapped[int] = mapped_column(Integer, default=0)


class Job(Base):
    """A background job run. Computed metrics are stored in result_json for re-display."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    module: Mapped[str] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text)
    error_reason: Mapped[str | None] = mapped_column(Text)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    max_requests: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
