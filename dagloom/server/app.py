"""FastAPI application factory.

Creates the Dagloom web server with REST API, WebSocket support,
and database lifecycle management.

Usage::

    uvicorn dagloom.server.app:create_app --factory
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from dagloom.scheduler.scheduler import SchedulerService
from dagloom.server.api import router as api_router
from dagloom.server.api import set_state, ws_manager
from dagloom.store.db import Database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle: database setup, scheduler, and teardown."""
    db = Database()
    await db.connect()
    set_state("db", db)

    # Start the built-in scheduler.
    scheduler = SchedulerService(db)
    await scheduler.start()
    set_state("scheduler", scheduler)

    logger.info("Dagloom server started.")
    yield

    await scheduler.stop()
    await db.close()
    logger.info("Dagloom server stopped.")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        A configured FastAPI instance.
    """
    app = FastAPI(
        title="Dagloom",
        description="A lightweight pipeline/workflow engine.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS for frontend dev server.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST API routes.
    app.include_router(api_router)

    # WebSocket endpoint.
    @app.websocket("/ws/{pipeline_id}")
    async def websocket_endpoint(websocket: WebSocket, pipeline_id: str) -> None:
        """WebSocket endpoint for real-time execution updates."""
        await ws_manager.connect(websocket, pipeline_id)
        try:
            while True:
                # Keep connection alive; handle incoming messages if needed.
                data = await websocket.receive_text()
                logger.debug("WS message from %s: %s", pipeline_id, data)
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket, pipeline_id)

    # Health check.
    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app
