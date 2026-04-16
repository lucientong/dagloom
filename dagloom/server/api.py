"""REST API routes for Dagloom server.

Provides endpoints for managing pipelines, triggering executions,
checking status, and interacting with the DAG structure.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dagloom.server.ws import ConnectionManager

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


# -- Request / Response models -----------------------------------------------


class RunRequest(BaseModel):
    """Request body for triggering a pipeline run."""

    inputs: dict[str, Any] = Field(default_factory=dict)


class DagUpdateRequest(BaseModel):
    """Request body for updating a DAG structure from the frontend."""

    nodes: list[dict[str, Any]]
    edges: list[list[str]]
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_hash: str | None = None  # For optimistic locking


class PipelineResponse(BaseModel):
    """Pipeline summary returned by list / get endpoints."""

    id: str
    name: str
    description: str = ""
    node_count: int = 0
    edge_count: int = 0
    updated_at: str = ""


class ExecutionResponse(BaseModel):
    """Execution status response."""

    execution_id: str
    pipeline_id: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None


class DagResponse(BaseModel):
    """DAG structure response."""

    nodes: list[dict[str, Any]]
    edges: list[list[str]]


class ScheduleRequest(BaseModel):
    """Request body for creating/updating a schedule."""

    pipeline_id: str
    cron_expr: str
    enabled: bool = True
    misfire_policy: str = "skip"


class ScheduleResponse(BaseModel):
    """Schedule information response."""

    id: str
    pipeline_id: str
    pipeline_name: str = ""
    cron_expr: str
    enabled: bool = True
    last_run: str | None = None
    next_run: str | None = None
    description: str = ""


class NotificationChannelRequest(BaseModel):
    """Request body for creating/updating a notification channel."""

    name: str
    type: str  # "email" or "webhook"
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class NotificationChannelResponse(BaseModel):
    """Notification channel response."""

    id: str
    name: str
    type: str
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class NotificationTestRequest(BaseModel):
    """Request body for sending a test notification."""

    channel_id: str
    pipeline_name: str = "test-pipeline"


# -- Shared state (injected by app.py lifespan) ------------------------------

_state: dict[str, Any] = {}
ws_manager = ConnectionManager()


def set_state(key: str, value: Any) -> None:
    """Set a shared state value (called during app startup)."""
    _state[key] = value


def get_state(key: str) -> Any:
    """Get a shared state value."""
    return _state.get(key)


# -- Endpoints ---------------------------------------------------------------


@router.get("/pipelines", response_model=list[PipelineResponse])
async def list_pipelines() -> list[dict[str, Any]]:
    """List all registered pipelines."""
    db = get_state("db")
    if db is None:
        return []
    pipelines = await db.list_pipelines()
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "description": p.get("description", ""),
            "node_count": len(json.loads(p.get("node_names", "[]"))),
            "edge_count": len(json.loads(p.get("edges", "[]"))),
            "updated_at": p.get("updated_at", ""),
        }
        for p in pipelines
    ]


@router.post("/pipelines/{pipeline_id}/run", response_model=ExecutionResponse)
async def run_pipeline(pipeline_id: str, body: RunRequest) -> dict[str, Any]:
    """Trigger a pipeline execution.

    The pipeline is executed asynchronously in a background task via
    ``AsyncExecutor``.  If the pipeline has registered ``Node`` objects
    (via ``set_state("pipelines", ...)``), real execution takes place;
    otherwise only the database status is updated.
    """
    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")

    pipeline = await db.get_pipeline(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id!r} not found.")

    execution_id = uuid.uuid4().hex[:12]
    now = datetime.now(UTC).isoformat()

    await db.save_execution(
        execution_id=execution_id,
        pipeline_id=pipeline_id,
        status="running",
        started_at=now,
    )

    # Broadcast start event.
    await ws_manager.broadcast(
        pipeline_id,
        {"type": "execution_started", "execution_id": execution_id},
    )

    # Try to run the pipeline for real if a Pipeline object is registered.
    registered_pipelines: dict[str, Any] = get_state("pipelines") or {}
    pipe_obj = registered_pipelines.get(pipeline_id)

    if pipe_obj is not None:
        asyncio.create_task(
            _run_pipeline_background(
                pipe_obj,
                execution_id,
                pipeline_id,
                body.inputs,
                db,
            )
        )

    return {
        "execution_id": execution_id,
        "pipeline_id": pipeline_id,
        "status": "running",
        "started_at": now,
    }


async def _run_pipeline_background(
    pipe_obj: Any,
    execution_id: str,
    pipeline_id: str,
    inputs: dict[str, Any],
    db: Any,
) -> None:
    """Execute a pipeline in the background and update DB status."""
    from dagloom.scheduler.executor import AsyncExecutor

    try:
        executor = AsyncExecutor(pipe_obj)
        await executor.execute(**inputs)

        now = datetime.now(UTC).isoformat()
        await db.save_execution(
            execution_id=execution_id,
            pipeline_id=pipeline_id,
            status="success",
            finished_at=now,
        )
        await ws_manager.broadcast(
            pipeline_id,
            {"type": "execution_completed", "execution_id": execution_id},
        )
    except Exception as exc:
        now = datetime.now(UTC).isoformat()
        await db.save_execution(
            execution_id=execution_id,
            pipeline_id=pipeline_id,
            status="failed",
            finished_at=now,
            error_message=str(exc),
        )
        await ws_manager.broadcast(
            pipeline_id,
            {
                "type": "execution_failed",
                "execution_id": execution_id,
                "error": str(exc),
            },
        )
        logger.error("Pipeline %s execution failed: %s", pipeline_id, exc)


@router.get("/pipelines/{pipeline_id}/status", response_model=ExecutionResponse)
async def get_pipeline_status(pipeline_id: str) -> dict[str, Any]:
    """Get the latest execution status for a pipeline."""
    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")

    # Get the most recent execution for this pipeline via Database helper.
    record = await db.get_latest_execution(pipeline_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"No executions found for pipeline {pipeline_id!r}."
        )

    return {
        "execution_id": record["id"],
        "pipeline_id": record["pipeline_id"],
        "status": record["status"],
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "error_message": record.get("error_message"),
    }


@router.post("/pipelines/{pipeline_id}/resume", response_model=ExecutionResponse)
async def resume_pipeline(pipeline_id: str) -> dict[str, Any]:
    """Resume a failed pipeline execution from checkpoint."""
    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")

    # Find the latest failed execution via Database helper.
    record = await db.get_latest_execution(pipeline_id, status="failed")
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No failed execution found for pipeline {pipeline_id!r}.",
        )

    execution_id = record["id"]
    now = datetime.now(UTC).isoformat()

    # Update the execution status to running (resume).
    await db.save_execution(
        execution_id=execution_id,
        pipeline_id=pipeline_id,
        status="running",
        started_at=now,
    )

    await ws_manager.broadcast(
        pipeline_id,
        {"type": "execution_resumed", "execution_id": execution_id},
    )

    return {
        "execution_id": execution_id,
        "pipeline_id": pipeline_id,
        "status": "running",
        "started_at": now,
    }


@router.get("/pipelines/{pipeline_id}/dag")
async def get_dag(pipeline_id: str) -> dict[str, Any]:
    """Get the DAG structure for frontend rendering.

    If the pipeline has an associated source file, the file is parsed
    to extract the full DAG (with function bodies and metadata).
    """
    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")

    pipeline = await db.get_pipeline(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id!r} not found.")

    source_file = pipeline.get("source_file")

    # If we have a source file, parse it for the richest DAG representation.
    if source_file:
        from pathlib import Path

        from dagloom.server.codegen import code_to_dag

        path = Path(source_file)
        if path.exists():
            source = path.read_text(encoding="utf-8")
            dag = code_to_dag(source)
            return dag

    # Fallback to DB-stored structure.
    nodes_raw = json.loads(pipeline.get("node_names", "[]"))
    edges_raw = json.loads(pipeline.get("edges", "[]"))
    nodes = [{"name": n, "id": n} for n in nodes_raw]
    return {"nodes": nodes, "edges": edges_raw, "metadata": {}, "source_hash": ""}


@router.put("/pipelines/{pipeline_id}/dag")
async def update_dag(pipeline_id: str, body: DagUpdateRequest) -> dict[str, Any]:
    """Update the DAG structure from frontend drag-and-drop.

    If the pipeline has an associated source file, the DAG is converted
    back to Python code and written to disk.  Includes optimistic locking
    via ``source_hash`` — returns 409 Conflict if the file was modified
    since the last read.
    """
    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")

    pipeline = await db.get_pipeline(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id!r} not found.")

    node_names = [n.get("name", n.get("id", "")) for n in body.nodes]
    edges = [tuple(e) for e in body.edges]

    # --- Optimistic locking: check source_hash if file exists ---
    source_file = pipeline.get("source_file")
    if source_file and body.source_hash:
        from pathlib import Path

        from dagloom.server.codegen import compute_source_hash

        path = Path(source_file)
        if path.exists():
            current_hash = compute_source_hash(path.read_text(encoding="utf-8"))
            if current_hash != body.source_hash:
                raise HTTPException(
                    status_code=409,
                    detail="File has been modified since last read. Reload the DAG and try again.",
                )

    # --- Write code to file if source_file is set ---
    new_hash = ""
    if source_file:
        from pathlib import Path

        from dagloom.server.codegen import compute_source_hash, dag_to_code

        dag_dict = {
            "nodes": body.nodes,
            "edges": body.edges,
            "metadata": body.metadata,
        }
        code = dag_to_code(dag_dict)
        path = Path(source_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        new_hash = compute_source_hash(code)

        # Tell the watcher to ignore this write.
        watcher = get_state("watcher")
        if watcher is not None:
            watcher.update_hash(source_file, new_hash)

    await db.save_pipeline(
        pipeline_id=pipeline_id,
        name=pipeline["name"],
        description=pipeline.get("description", ""),
        node_names=node_names,
        edges=edges,
        source_file=source_file,
    )

    await ws_manager.broadcast(
        pipeline_id,
        {"type": "dag_updated", "nodes": node_names, "edges": body.edges},
    )

    return {"status": "ok", "source_hash": new_hash}


# -- Schedule Endpoints ------------------------------------------------------


@router.get("/schedules", response_model=list[ScheduleResponse])
async def list_schedules() -> list[dict[str, Any]]:
    """List all registered schedules."""
    scheduler = get_state("scheduler")
    if scheduler is None:
        return []
    schedules = await scheduler.list_schedules()
    return [s.to_dict() for s in schedules]


@router.post("/schedules", response_model=ScheduleResponse)
async def create_schedule(body: ScheduleRequest) -> dict[str, Any]:
    """Create a new schedule for a pipeline."""
    from dagloom.scheduler.triggers import validate_expression

    scheduler = get_state("scheduler")
    if scheduler is None:
        raise HTTPException(status_code=500, detail="Scheduler not initialized.")

    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")

    # Validate cron expression.
    if not validate_expression(body.cron_expr):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid schedule expression: {body.cron_expr!r}",
        )

    # Verify pipeline exists.
    pipeline = await db.get_pipeline(body.pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pipeline {body.pipeline_id!r} not found.",
        )

    # Get the Pipeline object if registered.
    registered_pipelines: dict[str, Any] = get_state("pipelines") or {}
    pipe_obj = registered_pipelines.get(body.pipeline_id)

    if pipe_obj is not None:
        schedule_id = await scheduler.register(
            pipeline=pipe_obj,
            cron_expr=body.cron_expr,
            pipeline_id=body.pipeline_id,
            enabled=body.enabled,
            misfire_policy=body.misfire_policy,
        )
    else:
        # Register without pipeline object (will need to be set later).
        schedule_id = await scheduler.register(
            pipeline=None,
            cron_expr=body.cron_expr,
            pipeline_id=body.pipeline_id,
            enabled=body.enabled,
            misfire_policy=body.misfire_policy,
        )

    from dagloom.scheduler.triggers import describe_trigger

    return {
        "id": schedule_id,
        "pipeline_id": body.pipeline_id,
        "pipeline_name": pipeline.get("name", ""),
        "cron_expr": body.cron_expr,
        "enabled": body.enabled,
        "description": describe_trigger(body.cron_expr),
    }


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str) -> dict[str, str]:
    """Delete a schedule."""
    scheduler = get_state("scheduler")
    if scheduler is None:
        raise HTTPException(status_code=500, detail="Scheduler not initialized.")

    await scheduler.unregister(schedule_id)
    return {"status": "ok"}


@router.post("/schedules/{schedule_id}/pause")
async def pause_schedule(schedule_id: str) -> dict[str, str]:
    """Pause a schedule."""
    scheduler = get_state("scheduler")
    if scheduler is None:
        raise HTTPException(status_code=500, detail="Scheduler not initialized.")

    await scheduler.pause(schedule_id)
    return {"status": "ok"}


@router.post("/schedules/{schedule_id}/resume")
async def resume_schedule(schedule_id: str) -> dict[str, str]:
    """Resume a paused schedule."""
    scheduler = get_state("scheduler")
    if scheduler is None:
        raise HTTPException(status_code=500, detail="Scheduler not initialized.")

    await scheduler.resume(schedule_id)
    return {"status": "ok"}


# -- Notification Channel Endpoints ------------------------------------------


@router.get("/notifications", response_model=list[NotificationChannelResponse])
async def list_notification_channels() -> list[dict[str, Any]]:
    """List all notification channels."""
    db = get_state("db")
    if db is None:
        return []
    channels = await db.list_notification_channels()
    result = []
    for ch in channels:
        config = ch.get("config", "{}")
        if isinstance(config, str):
            config = json.loads(config)
        result.append(
            {
                "id": ch["id"],
                "name": ch["name"],
                "type": ch["type"],
                "config": config,
                "enabled": bool(ch.get("enabled", True)),
            }
        )
    return result


@router.post("/notifications", response_model=NotificationChannelResponse)
async def create_notification_channel(
    body: NotificationChannelRequest,
) -> dict[str, Any]:
    """Create a notification channel."""
    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")

    if body.type not in ("email", "webhook"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported channel type: {body.type!r}. Use 'email' or 'webhook'.",
        )

    channel_id = uuid.uuid4().hex[:12]
    await db.save_notification_channel(
        channel_id=channel_id,
        name=body.name,
        channel_type=body.type,
        config=body.config,
        enabled=body.enabled,
    )
    return {
        "id": channel_id,
        "name": body.name,
        "type": body.type,
        "config": body.config,
        "enabled": body.enabled,
    }


@router.delete("/notifications/{channel_id}")
async def delete_notification_channel(channel_id: str) -> dict[str, str]:
    """Delete a notification channel."""
    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")
    await db.delete_notification_channel(channel_id)
    return {"status": "ok"}


@router.post("/notifications/test")
async def test_notification(body: NotificationTestRequest) -> dict[str, str]:
    """Send a test notification through a configured channel."""
    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")

    channel_record = await db.get_notification_channel(body.channel_id)
    if channel_record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Channel {body.channel_id!r} not found.",
        )

    from dagloom.notifications.base import ExecutionEvent
    from dagloom.notifications.email import SMTPChannel
    from dagloom.notifications.webhook import WebhookChannel

    config = channel_record.get("config", "{}")
    if isinstance(config, str):
        config = json.loads(config)

    channel_type = channel_record["type"]
    if channel_type == "email":
        channel = SMTPChannel(**config)
    elif channel_type == "webhook":
        channel = WebhookChannel(**config)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown channel type: {channel_type!r}.",
        )

    event = ExecutionEvent(
        pipeline_name=body.pipeline_name,
        pipeline_id="test",
        execution_id="test-" + uuid.uuid4().hex[:8],
        status="success",
        duration_seconds=1.23,
        node_count=3,
    )

    try:
        await channel.send(event)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Notification delivery failed: {exc}",
        ) from exc

    return {"status": "ok", "message": "Test notification sent successfully."}


# -- Metrics / History endpoints -----------------------------------------------


@router.get("/metrics/{pipeline_id}")
async def get_metrics(pipeline_id: str) -> dict[str, Any]:
    """Get per-node aggregate metrics for a pipeline.

    Returns node-level stats: total runs, success/failure counts,
    avg/min/max/p50/p95 wall-time in milliseconds.
    """
    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")

    stats = await db.get_node_stats(pipeline_id)
    return {
        "pipeline_id": pipeline_id,
        "nodes": stats,
    }


@router.get("/history/{pipeline_id}")
async def get_history(
    pipeline_id: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Get execution history for a pipeline with per-node metrics.

    Args:
        pipeline_id: Pipeline to query.
        limit: Max executions to return (default 20).
    """
    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")

    executions = await db.get_execution_history(pipeline_id, limit=limit)
    return {
        "pipeline_id": pipeline_id,
        "executions": executions,
    }


# -- Secrets endpoints --------------------------------------------------------


class SecretCreateRequest(BaseModel):
    """Request body for creating/updating a secret."""

    key: str = Field(..., description="Secret key name.")
    value: str = Field(..., description="Plaintext secret value.")


@router.get("/secrets")
async def list_secrets() -> list[dict[str, Any]]:
    """List all secret keys (values are never exposed)."""
    db = _state["db"]
    rows = await db.list_secrets()
    return [
        {"key": r["key"], "created_at": r["created_at"], "updated_at": r["updated_at"]}
        for r in rows
    ]


@router.post("/secrets", status_code=201)
async def create_secret(body: SecretCreateRequest) -> dict[str, Any]:
    """Create or update an encrypted secret."""
    from dagloom.security.encryption import Encryptor

    encryptor = _state.get("encryptor")
    if encryptor is None:
        encryptor = Encryptor()
        _state["encryptor"] = encryptor

    db = _state["db"]
    encrypted = encryptor.encrypt(body.value)
    await db.save_secret(body.key, encrypted)
    return {"key": body.key, "status": "created"}


@router.delete("/secrets/{key}")
async def delete_secret(key: str) -> dict[str, str]:
    """Delete a secret by key."""
    db = _state["db"]
    existing = await db.get_secret(key)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Secret {key!r} not found.")
    await db.delete_secret(key)
    return {"key": key, "status": "deleted"}
