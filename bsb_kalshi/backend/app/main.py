"""FastAPI application entry point: ``uvicorn app.main:app`` from the backend directory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.notes_file import restore_empty_notes
from app.modules import (
    ingame,
    m0_core,
    m1_endpoints,
    m2_schema,
    m3_timestamps,
    m4_depth,
    m5_limits,
    m6_rest_ws,
    m7_sportsbook,
    m8_export,
    t3_nfl_costs,
    t4_sportsbook,
)
from app.services import Services


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build services and fill empty notes from the tracked notes file; on shutdown stop jobs."""
    services = Services.build(get_settings())
    restore_empty_notes(services.db, services.config.notes_file)
    app.state.services = services
    try:
        yield
    finally:
        services.jobs.stop_all()
        await services.client.aclose()


app = FastAPI(title="Kalshi Recon", version="0.4.0", lifespan=lifespan)
for module in (
    m0_core,
    m1_endpoints,
    m2_schema,
    m3_timestamps,
    m4_depth,
    m5_limits,
    m6_rest_ws,
    m7_sportsbook,
    m8_export,
    t3_nfl_costs,
    t4_sportsbook,
    ingame,
):
    app.include_router(module.router)
