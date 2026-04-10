"""REST API routes for Dagloom server.

Provides endpoints for managing pipelines, triggering executions,
checking status, and interacting with the DAG structure.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dagloom.server.ws import ConnectionManager

router = APIRouter(prefix="/api")


# -- Request / Response models -----------------------------------------------


class RunRequest(BaseModel):
    """Request body for triggering a pipeline run."""

    inputs: dict[str, Any] = Field(default_factory=dict)


class DagUpdateRequest(BaseModel):
    """Request body for updating a DAG structure from the frontend."""

    nodes: list[dict[str, Any]]
    edges: list[list[str]]


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
    """Trigger a pipeline execution."""
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

    return {
        "execution_id": execution_id,
        "pipeline_id": pipeline_id,
        "status": "running",
        "started_at": now,
    }


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


@router.get("/pipelines/{pipeline_id}/dag", response_model=DagResponse)
async def get_dag(pipeline_id: str) -> dict[str, Any]:
    """Get the DAG structure for frontend rendering."""
    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")

    pipeline = await db.get_pipeline(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id!r} not found.")

    nodes_raw = json.loads(pipeline.get("node_names", "[]"))
    edges_raw = json.loads(pipeline.get("edges", "[]"))

    nodes = [{"name": n, "id": n} for n in nodes_raw]
    return {"nodes": nodes, "edges": edges_raw}


@router.put("/pipelines/{pipeline_id}/dag")
async def update_dag(pipeline_id: str, body: DagUpdateRequest) -> dict[str, str]:
    """Update the DAG structure from frontend drag-and-drop."""
    db = get_state("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized.")

    pipeline = await db.get_pipeline(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id!r} not found.")

    node_names = [n.get("name", n.get("id", "")) for n in body.nodes]
    edges = [tuple(e) for e in body.edges]

    await db.save_pipeline(
        pipeline_id=pipeline_id,
        name=pipeline["name"],
        description=pipeline.get("description", ""),
        node_names=node_names,
        edges=edges,
    )

    await ws_manager.broadcast(
        pipeline_id,
        {"type": "dag_updated", "nodes": node_names, "edges": body.edges},
    )

    return {"status": "ok"}
