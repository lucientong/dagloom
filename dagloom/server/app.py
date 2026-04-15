"""FastAPI application factory.

Creates the Dagloom web server with REST API, WebSocket support,
and database lifecycle management.

Supports authentication via CLI options:
- --auth-type: Type of authentication (API_KEY, BASIC_AUTH, NONE)
- --auth-key: API key or username:password for basic auth

Usage::

    uvicorn dagloom.server.app:create_app --factory
    dagloom serve --auth-type API_KEY --auth-key sk-abc123
    dagloom serve --auth-type BASIC_AUTH --auth-key admin:password
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from dagloom.scheduler.scheduler import SchedulerService
from dagloom.server.api import router as api_router
from dagloom.server.api import set_state, ws_manager
from dagloom.server.middleware import AuthMiddleware
from dagloom.server.watcher import PipelineWatcher
from dagloom.store.db import Database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle: database setup, scheduler, watcher, and teardown."""
    db = Database()
    await db.connect()
    set_state("db", db)

    # Start the built-in scheduler.
    scheduler = SchedulerService(db)
    await scheduler.start()
    set_state("scheduler", scheduler)

    # Start the file watcher for bidirectional code <-> UI sync.
    async def _on_file_change(file_path: str, dag: dict[str, Any]) -> None:
        """Broadcast DAG updates when a pipeline file changes."""
        # Try to find the pipeline_id associated with this file.
        pipelines = await db.list_pipelines()
        for p in pipelines:
            if p.get("source_file") == file_path:
                await ws_manager.broadcast(
                    p["id"],
                    {
                        "type": "dag_updated",
                        "nodes": [n.get("name", "") for n in dag.get("nodes", [])],
                        "edges": dag.get("edges", []),
                        "source_file": file_path,
                    },
                )
                break

    watcher = PipelineWatcher(watch_dirs=["."], on_change=_on_file_change)
    await watcher.start()
    set_state("watcher", watcher)

    logger.info("Dagloom server started.")
    yield

    await watcher.stop()
    await scheduler.stop()
    await db.close()
    logger.info("Dagloom server stopped.")


def _create_auth_provider(auth_type: str | None, auth_key: str | None) -> Any | None:
    """Create an authentication provider based on CLI arguments.

    Args:
        auth_type: Type of authentication (API_KEY, BASIC_AUTH, or None/NONE).
        auth_key: Credentials for the auth type.

    Returns:
        An AuthProvider instance, or None if no auth is configured.

    Raises:
        ValueError: If auth_type is invalid or auth_key is missing.
    """
    if auth_type is None or auth_type.upper() == "NONE":
        return None

    auth_type_upper = auth_type.upper()

    if auth_type_upper == "API_KEY":
        from dagloom.security.auth import APIKeyAuth

        if not auth_key:
            raise ValueError("--auth-key is required for API_KEY authentication")
        logger.info("Initializing API Key authentication")
        return APIKeyAuth(api_key=auth_key)

    if auth_type_upper == "BASIC_AUTH":
        from dagloom.security.auth import BasicAuth

        if not auth_key:
            raise ValueError("--auth-key is required for BASIC_AUTH authentication")
        # Expected format: username:password
        if ":" not in auth_key:
            raise ValueError("--auth-key for BASIC_AUTH must be in format: username:password")
        username, password = auth_key.split(":", 1)
        logger.info("Initializing Basic Auth authentication for user %r", username)
        return BasicAuth(username=username, password=password)

    raise ValueError(f"Unknown authentication type: {auth_type}")


def create_app(
    auth_type: str | None = None,
    auth_key: str | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        auth_type: Type of authentication (API_KEY, BASIC_AUTH, or None).
            Can also be set via DAGLOOM_AUTH_TYPE environment variable.
        auth_key: Credentials for the auth type.
            Can also be set via DAGLOOM_AUTH_KEY environment variable.

    Returns:
        A configured FastAPI instance.
    """
    # Check environment variables if CLI args not provided.
    if auth_type is None:
        auth_type = os.environ.get("DAGLOOM_AUTH_TYPE")
    if auth_key is None:
        auth_key = os.environ.get("DAGLOOM_AUTH_KEY")

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

    # Authentication middleware (if configured).
    try:
        auth_provider = _create_auth_provider(auth_type, auth_key)
        if auth_provider is not None:
            app.add_middleware(
                AuthMiddleware,
                auth_provider=auth_provider,
            )
            logger.info("Authentication middleware enabled: %s", auth_type)
    except ValueError as exc:
        logger.error("Failed to initialize authentication: %s", exc)
        raise

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
