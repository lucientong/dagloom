"""Pydantic data models for Dagloom storage layer.

These models define the schema for pipeline definitions, execution
records, node execution states, and cache entries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeStatus(str, Enum):
    """Status of a node execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineModel(BaseModel):
    """Stored pipeline definition."""

    id: str
    name: str
    description: str = ""
    node_names: list[str] = Field(default_factory=list)
    edges: list[tuple[str, str]] = Field(default_factory=list)
    source_file: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionModel(BaseModel):
    """Record of a pipeline execution run."""

    id: str
    pipeline_id: str
    status: NodeStatus = NodeStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NodeExecutionModel(BaseModel):
    """Record of a single node's execution within a pipeline run."""

    pipeline_id: str
    execution_id: str
    node_id: str
    status: NodeStatus = NodeStatus.PENDING
    input_hash: str | None = None
    output_path: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None


class CacheEntryModel(BaseModel):
    """Metadata for a cached node output."""

    node_id: str
    input_hash: str
    output_path: str
    serialization_format: str = "pickle"  # pickle | json | parquet
    size_bytes: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
