"""Checkpoint and resume for pipeline execution.

Persists node execution states to SQLite so that a failed pipeline can
be resumed from the last successful checkpoint using ``dagloom resume``.

Example::

    ckpt = CheckpointManager(db)
    await ckpt.save_state(exec_id, pipeline_id, "clean", "success")
    completed = await ckpt.get_completed_nodes(exec_id)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from dagloom.store.db import Database

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Manage checkpoint state for pipeline executions.

    Nodes' execution states (PENDING / RUNNING / SUCCESS / FAILED) are
    persisted to SQLite.  On resume, completed nodes are skipped and
    execution continues from the failed or pending nodes.

    Args:
        db: Database instance.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    async def save_state(
        self,
        execution_id: str,
        pipeline_id: str,
        node_id: str,
        status: str,
        input_hash: str | None = None,
        output_path: str | None = None,
        error_message: str | None = None,
        retry_count: int = 0,
    ) -> None:
        """Persist the execution state of a single node.

        Args:
            execution_id: The execution run ID.
            pipeline_id: The pipeline ID.
            node_id: The node whose state to save.
            status: One of "pending", "running", "success", "failed".
            input_hash: Hash of the node's input (optional).
            output_path: Path to cached output (optional).
            error_message: Error description if failed.
            retry_count: Number of retries attempted.
        """
        now = datetime.now(timezone.utc).isoformat()
        started_at = now if status == "running" else None
        finished_at = now if status in ("success", "failed") else None

        await self.db.save_node_execution(
            pipeline_id=pipeline_id,
            execution_id=execution_id,
            node_id=node_id,
            status=status,
            input_hash=input_hash,
            output_path=output_path,
            error_message=error_message,
            retry_count=retry_count,
            started_at=started_at,
            finished_at=finished_at,
        )
        logger.debug(
            "Checkpoint: %s/%s status=%s", execution_id, node_id, status
        )

    async def get_completed_nodes(self, execution_id: str) -> set[str]:
        """Return the set of successfully completed node IDs.

        Args:
            execution_id: The execution run to query.

        Returns:
            Set of node names that have status "success".
        """
        return await self.db.get_completed_nodes(execution_id)

    async def get_node_states(
        self, execution_id: str
    ) -> dict[str, str]:
        """Return a mapping of node_id -> status for all nodes.

        Args:
            execution_id: The execution run to query.

        Returns:
            Dict mapping node name to its status string.
        """
        records = await self.db.get_node_executions(execution_id)
        return {r["node_id"]: r["status"] for r in records}

    async def should_skip(self, execution_id: str, node_id: str) -> bool:
        """Check whether a node should be skipped during resume.

        A node is skipped if it already succeeded in the given execution.

        Args:
            execution_id: The execution run to check.
            node_id: The node to check.

        Returns:
            True if the node should be skipped.
        """
        completed = await self.get_completed_nodes(execution_id)
        return node_id in completed

    async def init_execution(
        self,
        execution_id: str,
        pipeline_id: str,
    ) -> None:
        """Initialize an execution record.

        Args:
            execution_id: Unique execution ID.
            pipeline_id: The pipeline being executed.
        """
        now = datetime.now(timezone.utc).isoformat()
        await self.db.save_execution(
            execution_id=execution_id,
            pipeline_id=pipeline_id,
            status="running",
            started_at=now,
        )

    async def finish_execution(
        self,
        execution_id: str,
        pipeline_id: str,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """Mark an execution as finished.

        Args:
            execution_id: The execution run ID.
            pipeline_id: The pipeline ID.
            success: Whether the execution succeeded.
            error_message: Error description if failed.
        """
        now = datetime.now(timezone.utc).isoformat()
        await self.db.save_execution(
            execution_id=execution_id,
            pipeline_id=pipeline_id,
            status="success" if success else "failed",
            finished_at=now,
            error_message=error_message,
        )
