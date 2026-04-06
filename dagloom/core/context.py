"""Execution context for pipeline runs.

The ``ExecutionContext`` carries data between nodes and records metadata
about each node's execution (start time, duration, status, errors).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class NodeStatus(StrEnum):
    """Status of a node execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class NodeExecutionInfo:
    """Metadata recorded for a single node execution.

    Attributes:
        node_name: Name of the executed node.
        status: Current execution status.
        started_at: Monotonic timestamp when execution started.
        finished_at: Monotonic timestamp when execution finished.
        duration: Elapsed time in seconds.
        error: Error message if the node failed.
        retry_count: Number of retries attempted before final status.
    """

    node_name: str
    status: NodeStatus = NodeStatus.PENDING
    started_at: float | None = None
    finished_at: float | None = None
    duration: float | None = None
    error: str | None = None
    retry_count: int = 0

    def mark_running(self) -> None:
        """Mark this node as currently running."""
        self.status = NodeStatus.RUNNING
        self.started_at = time.monotonic()

    def mark_success(self) -> None:
        """Mark this node as successfully completed."""
        self.status = NodeStatus.SUCCESS
        self.finished_at = time.monotonic()
        if self.started_at is not None:
            self.duration = self.finished_at - self.started_at

    def mark_failed(self, error: str) -> None:
        """Mark this node as failed with an error message."""
        self.status = NodeStatus.FAILED
        self.finished_at = time.monotonic()
        self.error = error
        if self.started_at is not None:
            self.duration = self.finished_at - self.started_at

    def mark_skipped(self) -> None:
        """Mark this node as skipped (e.g. cache hit)."""
        self.status = NodeStatus.SKIPPED


@dataclass
class ExecutionContext:
    """Manages data flow and metadata for a pipeline execution.

    Each pipeline run creates a fresh ``ExecutionContext`` that:
    - Stores outputs produced by each node (keyed by node name).
    - Records execution metadata for every node.
    - Provides a unique execution ID for tracking.

    Attributes:
        execution_id: Unique identifier for this pipeline run.
        pipeline_name: Name of the pipeline being executed.
        outputs: Mapping of node name to its output value.
        node_info: Mapping of node name to its execution metadata.
        metadata: Arbitrary user-defined metadata.
    """

    execution_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    pipeline_name: str = ""
    outputs: dict[str, Any] = field(default_factory=dict)
    node_info: dict[str, NodeExecutionInfo] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def set_output(self, node_name: str, value: Any) -> None:
        """Store the output of a node.

        Args:
            node_name: The node that produced the output.
            value: The output value.
        """
        self.outputs[node_name] = value

    def get_output(self, node_name: str) -> Any:
        """Retrieve the output of a node.

        Args:
            node_name: The node whose output to retrieve.

        Returns:
            The stored output value.

        Raises:
            KeyError: If the node has not produced output yet.
        """
        if node_name not in self.outputs:
            raise KeyError(
                f"Node {node_name!r} has not produced output yet. "
                f"Available outputs: {list(self.outputs.keys())}"
            )
        return self.outputs[node_name]

    def has_output(self, node_name: str) -> bool:
        """Check whether a node has produced output.

        Args:
            node_name: The node to check.

        Returns:
            True if the node has stored output.
        """
        return node_name in self.outputs

    def get_node_info(self, node_name: str) -> NodeExecutionInfo:
        """Get or create execution info for a node.

        Args:
            node_name: The node to look up.

        Returns:
            The ``NodeExecutionInfo`` instance.
        """
        if node_name not in self.node_info:
            self.node_info[node_name] = NodeExecutionInfo(node_name=node_name)
        return self.node_info[node_name]

    @property
    def is_complete(self) -> bool:
        """True when all tracked nodes have finished (success, failed, or skipped)."""
        terminal = {NodeStatus.SUCCESS, NodeStatus.FAILED, NodeStatus.SKIPPED}
        return all(info.status in terminal for info in self.node_info.values())

    @property
    def is_success(self) -> bool:
        """True when all tracked nodes succeeded or were skipped."""
        ok = {NodeStatus.SUCCESS, NodeStatus.SKIPPED}
        return all(info.status in ok for info in self.node_info.values())

    @property
    def failed_nodes(self) -> list[str]:
        """Return names of all nodes that failed."""
        return [name for name, info in self.node_info.items() if info.status == NodeStatus.FAILED]

    def summary(self) -> dict[str, Any]:
        """Return a summary dict suitable for logging or serialization."""
        return {
            "execution_id": self.execution_id,
            "pipeline_name": self.pipeline_name,
            "is_complete": self.is_complete,
            "is_success": self.is_success,
            "nodes": {
                name: {
                    "status": info.status.value,
                    "duration": info.duration,
                    "error": info.error,
                    "retry_count": info.retry_count,
                }
                for name, info in self.node_info.items()
            },
        }
