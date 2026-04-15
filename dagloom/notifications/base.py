"""Notification channel base classes and event data model.

Defines the abstract interface for notification channels and the
``ExecutionEvent`` dataclass that carries execution results to channels.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExecutionEvent:
    """Data passed to notification channels after pipeline execution.

    Attributes:
        pipeline_name: Human-readable pipeline name.
        pipeline_id: Unique pipeline identifier.
        execution_id: Unique execution identifier.
        status: Execution outcome — ``"success"`` or ``"failed"``.
        started_at: ISO timestamp when execution started.
        finished_at: ISO timestamp when execution finished.
        error_message: Error details if the execution failed.
        duration_seconds: Wall-clock execution time.
        node_count: Total number of nodes in the pipeline.
        failed_node: Name of the node that caused failure, if any.
        metadata: Arbitrary extra data.
    """

    pipeline_name: str
    pipeline_id: str = ""
    execution_id: str = ""
    status: str = "success"
    started_at: str = ""
    finished_at: str = ""
    error_message: str | None = None
    duration_seconds: float = 0.0
    node_count: int = 0
    failed_node: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.finished_at:
            self.finished_at = datetime.now(UTC).isoformat()

    @property
    def is_success(self) -> bool:
        """Whether the execution succeeded."""
        return self.status == "success"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON payloads."""
        return {
            "pipeline_name": self.pipeline_name,
            "pipeline_id": self.pipeline_id,
            "execution_id": self.execution_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds,
            "node_count": self.node_count,
            "failed_node": self.failed_node,
            "metadata": self.metadata,
        }

    def summary(self) -> str:
        """One-line human-readable summary."""
        icon = "\u2705" if self.is_success else "\u274c"
        msg = f"{icon} Pipeline '{self.pipeline_name}' {self.status}"
        if self.duration_seconds:
            msg += f" in {self.duration_seconds:.1f}s"
        if self.error_message:
            msg += f" — {self.error_message}"
        return msg


class NotificationChannel(ABC):
    """Abstract base class for notification channels.

    Subclasses must implement :meth:`send` to deliver the notification
    via a specific transport (SMTP, HTTP webhook, etc.).
    """

    @abstractmethod
    async def send(self, event: ExecutionEvent) -> None:
        """Send a notification for the given execution event.

        Args:
            event: The execution event to report.

        Raises:
            Exception: If the notification delivery fails.
        """

    async def close(self) -> None:  # noqa: B027
        """Clean up resources (optional override)."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"
