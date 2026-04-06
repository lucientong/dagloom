"""WebSocket connection manager for real-time status push.

Manages multiple WebSocket clients and broadcasts execution events
such as node status changes and log messages.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manage WebSocket connections and broadcast messages.

    Maintains a set of active connections grouped by pipeline ID so
    that clients only receive events for the pipeline they are watching.
    """

    def __init__(self) -> None:
        # pipeline_id -> set of active websockets
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, pipeline_id: str) -> None:
        """Accept a WebSocket connection and register it.

        Args:
            websocket: The incoming WebSocket connection.
            pipeline_id: The pipeline this client is watching.
        """
        await websocket.accept()
        if pipeline_id not in self._connections:
            self._connections[pipeline_id] = set()
        self._connections[pipeline_id].add(websocket)
        logger.info(
            "WebSocket connected for pipeline %s (total=%d)",
            pipeline_id,
            len(self._connections[pipeline_id]),
        )

    def disconnect(self, websocket: WebSocket, pipeline_id: str) -> None:
        """Remove a WebSocket connection.

        Args:
            websocket: The disconnected WebSocket.
            pipeline_id: The pipeline it was watching.
        """
        if pipeline_id in self._connections:
            self._connections[pipeline_id].discard(websocket)
            if not self._connections[pipeline_id]:
                del self._connections[pipeline_id]

    async def broadcast(self, pipeline_id: str, message: dict[str, Any]) -> None:
        """Send a message to all clients watching a pipeline.

        Args:
            pipeline_id: The pipeline whose watchers to notify.
            message: JSON-serializable message dict.
        """
        if pipeline_id not in self._connections:
            return

        payload = json.dumps(message)
        dead: list[WebSocket] = []

        for ws in self._connections[pipeline_id]:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        # Clean up dead connections.
        for ws in dead:
            self._connections[pipeline_id].discard(ws)

    async def send_node_status(
        self,
        pipeline_id: str,
        execution_id: str,
        node_id: str,
        status: str,
        **extra: Any,
    ) -> None:
        """Broadcast a node status change event.

        Args:
            pipeline_id: The pipeline ID.
            execution_id: The execution run ID.
            node_id: The node whose status changed.
            status: The new status string.
            **extra: Additional fields (e.g. error_message).
        """
        await self.broadcast(
            pipeline_id,
            {
                "type": "node_status",
                "execution_id": execution_id,
                "node_id": node_id,
                "status": status,
                **extra,
            },
        )

    async def send_log(
        self,
        pipeline_id: str,
        execution_id: str,
        node_id: str,
        message: str,
        level: str = "info",
    ) -> None:
        """Broadcast a log message.

        Args:
            pipeline_id: The pipeline ID.
            execution_id: The execution run ID.
            node_id: The node that produced the log.
            message: The log message text.
            level: Log level (info, warning, error).
        """
        await self.broadcast(
            pipeline_id,
            {
                "type": "log",
                "execution_id": execution_id,
                "node_id": node_id,
                "message": message,
                "level": level,
            },
        )
