"""Shared fixtures. Tests use throwaway keys and a mocked transport; no network, no real key."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import FastAPI
from pydantic import SecretStr

from app.config import ROOT_DIR, Settings
from app.db import Database
from app.evidence import EvidenceLog
from app.jobs import TERMINAL_STATUSES, JobManager
from app.kalshi_client import KalshiClient, TokenBucket
from app.modules import (
    m0_core,
    m1_endpoints,
    m3_timestamps,
    m4_depth,
    m5_limits,
    m6_rest_ws,
    m7_sportsbook,
    m8_export,
)
from app.services import Services
from app.settings_store import SettingsStore
from app.spec_loader import AsyncApiSpec, OpenApiSpec

TEST_KEY_ID = "test-key-id-0000-throwaway"
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(scope="session")
def spec() -> OpenApiSpec:
    """The real OpenAPI spec from /specs."""
    return OpenApiSpec.load(ROOT_DIR / "specs" / "openapi.yaml")


@pytest.fixture(scope="session")
def throwaway_rsa_key() -> RSAPrivateKey:
    """A freshly generated RSA key used only by tests."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class Stack:
    """A fully wired client with a recording mock transport."""

    client: KalshiClient
    evidence: EvidenceLog
    jobs: JobManager
    bucket: TokenBucket
    settings: SettingsStore
    sent: list[httpx.Request] = field(default_factory=list)


@pytest.fixture
async def make_stack(
    tmp_path: Path, spec: OpenApiSpec, throwaway_rsa_key: RSAPrivateKey
) -> AsyncIterator[Callable[[Handler], Stack]]:
    """Factory building a Stack whose transport answers with ``handler``."""
    key_path = tmp_path / "throwaway.pem"
    key_path.write_bytes(
        throwaway_rsa_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    config = Settings(
        _env_file=None,  # type: ignore[call-arg]
        kalshi_key_id=SecretStr(TEST_KEY_ID),
        kalshi_private_key_path=key_path,
        data_dir=tmp_path,
        notes_file=tmp_path / "notes" / "answers.json",
        max_transport_retries=2,
        default_rate_limit_rps=20.0,
        default_rate_limit_burst=50,
    )
    (tmp_path / "raw").mkdir(exist_ok=True)
    stacks: list[Stack] = []

    def factory(handler: Handler) -> Stack:
        sent: list[httpx.Request] = []

        def recording(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return handler(request)

        db = Database(tmp_path / f"test{len(stacks)}.db")
        settings = SettingsStore(db, config, spec)
        evidence = EvidenceLog(db, tmp_path / "raw", [TEST_KEY_ID])
        jobs = JobManager(db, [TEST_KEY_ID])
        bucket = TokenBucket(1000.0, 50)
        client = KalshiClient(
            config, spec, settings, evidence, jobs, bucket, transport=httpx.MockTransport(recording)
        )
        stack = Stack(client, evidence, jobs, bucket, settings, sent)
        stacks.append(stack)
        return stack

    yield factory
    for stack in stacks:
        await stack.client.aclose()


@dataclass
class AppStack:
    """All API routers on a FastAPI app whose Kalshi client uses a mock transport."""

    http: httpx.AsyncClient
    services: Services
    sent: list[httpx.Request]


MakeApp = Callable[[Handler], AppStack]


@pytest.fixture
async def make_app(
    tmp_path: Path, spec: OpenApiSpec, throwaway_rsa_key: RSAPrivateKey
) -> AsyncIterator[MakeApp]:
    """Factory building an AppStack (one per test) whose transport answers with ``handler``."""
    key_text = throwaway_rsa_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    config = Settings(
        _env_file=None,  # type: ignore[call-arg]
        kalshi_key_id=SecretStr(TEST_KEY_ID),
        kalshi_private_key=SecretStr(key_text),
        data_dir=tmp_path,
        notes_file=tmp_path / "notes" / "answers.json",
        max_transport_retries=0,
        default_rate_limit_rps=20.0,
        default_rate_limit_burst=50,
    )
    for directory in (config.raw_dir, config.exports_dir):
        directory.mkdir(parents=True, exist_ok=True)
    built: list[AppStack] = []

    def factory(handler: Handler) -> AppStack:
        sent: list[httpx.Request] = []

        def recording(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return handler(request)

        db = Database(config.db_path)
        settings = SettingsStore(db, config, spec)
        evidence = EvidenceLog(db, config.raw_dir, [TEST_KEY_ID])
        jobs = JobManager(db, [TEST_KEY_ID])
        bucket = TokenBucket(1000.0, 50)
        client = KalshiClient(
            config, spec, settings, evidence, jobs, bucket, transport=httpx.MockTransport(recording)
        )
        asyncspec = AsyncApiSpec.load(config.specs_dir / "asyncapi.yaml")
        services = Services(config, db, spec, asyncspec, settings, evidence, jobs, bucket, client)
        app = FastAPI()
        for module in (m0_core, m1_endpoints, m3_timestamps, m4_depth, m5_limits, m6_rest_ws, m7_sportsbook, m8_export):
            app.include_router(module.router)
        app.state.services = services
        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        stack = AppStack(http, services, sent)
        built.append(stack)
        return stack

    yield factory
    for stack in built:
        stack.services.jobs.stop_all()
        await stack.http.aclose()
        await stack.services.client.aclose()


async def wait_for_job(services: Services, job_id: str, timeout_s: float = 10.0) -> dict[str, Any]:
    """Poll the job table until the job reaches a terminal status."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        job = services.jobs.get_job(job_id)
        if job is not None and job["status"] in TERMINAL_STATUSES:
            return job
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish within {timeout_s}s")
