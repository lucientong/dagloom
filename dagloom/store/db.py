"""SQLite storage layer for Dagloom.

Provides an async wrapper around SQLite via aiosqlite, managing
pipeline definitions, execution records, node execution states,
and cache metadata.  Uses WAL mode for improved concurrent performance.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = ".dagloom/dagloom.db"

# -- Schema DDL ---------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pipelines (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    node_names  TEXT DEFAULT '[]',
    edges       TEXT DEFAULT '[]',
    source_file TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS executions (
    id            TEXT PRIMARY KEY,
    pipeline_id   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    started_at    TEXT,
    finished_at   TEXT,
    error_message TEXT,
    metadata      TEXT DEFAULT '{}',
    FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
);

CREATE TABLE IF NOT EXISTS node_executions (
    pipeline_id   TEXT NOT NULL,
    execution_id  TEXT NOT NULL,
    node_id       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    input_hash    TEXT,
    output_path   TEXT,
    error_message TEXT,
    retry_count   INTEGER DEFAULT 0,
    started_at    TEXT,
    finished_at   TEXT,
    PRIMARY KEY (execution_id, node_id),
    FOREIGN KEY (execution_id) REFERENCES executions(id)
);

CREATE TABLE IF NOT EXISTS cache_entries (
    node_id              TEXT NOT NULL,
    input_hash           TEXT NOT NULL,
    output_path          TEXT NOT NULL,
    serialization_format TEXT DEFAULT 'pickle',
    size_bytes           INTEGER DEFAULT 0,
    created_at           TEXT NOT NULL,
    expires_at           TEXT,
    PRIMARY KEY (node_id, input_hash)
);
"""


class Database:
    """Async SQLite database wrapper.

    Args:
        db_path: Path to the SQLite database file. Parent directories
                 are created automatically.
    """

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database connection and initialise the schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row

        # Enable WAL mode for better concurrent reads.
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

        # Create tables.
        await self._conn.executescript(_SCHEMA_SQL)
        await self._conn.commit()
        logger.info("Database connected: %s", self.db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Database closed.")

    @property
    def conn(self) -> aiosqlite.Connection:
        """Return the active connection or raise."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    # -- Pipeline CRUD --------------------------------------------------------

    async def save_pipeline(
        self,
        pipeline_id: str,
        name: str,
        description: str = "",
        node_names: list[str] | None = None,
        edges: list[tuple[str, str]] | None = None,
        source_file: str | None = None,
    ) -> None:
        """Insert or update a pipeline definition."""
        now = datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            INSERT INTO pipelines (id, name, description, node_names, edges, source_file, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                description=excluded.description,
                node_names=excluded.node_names,
                edges=excluded.edges,
                source_file=excluded.source_file,
                updated_at=excluded.updated_at
            """,
            (
                pipeline_id,
                name,
                description,
                json.dumps(node_names or []),
                json.dumps(edges or []),
                source_file,
                now,
                now,
            ),
        )
        await self.conn.commit()

    async def get_pipeline(self, pipeline_id: str) -> dict[str, Any] | None:
        """Fetch a pipeline by ID."""
        cursor = await self.conn.execute(
            "SELECT * FROM pipelines WHERE id = ?", (pipeline_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    async def list_pipelines(self) -> list[dict[str, Any]]:
        """List all pipelines."""
        cursor = await self.conn.execute(
            "SELECT * FROM pipelines ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    # -- Execution CRUD -------------------------------------------------------

    async def save_execution(
        self,
        execution_id: str,
        pipeline_id: str,
        status: str = "pending",
        started_at: str | None = None,
        finished_at: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert or update an execution record."""
        await self.conn.execute(
            """
            INSERT INTO executions (id, pipeline_id, status, started_at, finished_at, error_message, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                started_at=COALESCE(excluded.started_at, executions.started_at),
                finished_at=excluded.finished_at,
                error_message=excluded.error_message,
                metadata=excluded.metadata
            """,
            (
                execution_id,
                pipeline_id,
                status,
                started_at,
                finished_at,
                error_message,
                json.dumps(metadata or {}),
            ),
        )
        await self.conn.commit()

    async def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        """Fetch an execution record by ID."""
        cursor = await self.conn.execute(
            "SELECT * FROM executions WHERE id = ?", (execution_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    # -- Node Execution CRUD --------------------------------------------------

    async def save_node_execution(
        self,
        pipeline_id: str,
        execution_id: str,
        node_id: str,
        status: str = "pending",
        input_hash: str | None = None,
        output_path: str | None = None,
        error_message: str | None = None,
        retry_count: int = 0,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        """Insert or update a node execution record."""
        await self.conn.execute(
            """
            INSERT INTO node_executions
                (pipeline_id, execution_id, node_id, status, input_hash,
                 output_path, error_message, retry_count, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(execution_id, node_id) DO UPDATE SET
                status=excluded.status,
                input_hash=COALESCE(excluded.input_hash, node_executions.input_hash),
                output_path=COALESCE(excluded.output_path, node_executions.output_path),
                error_message=excluded.error_message,
                retry_count=excluded.retry_count,
                started_at=COALESCE(excluded.started_at, node_executions.started_at),
                finished_at=excluded.finished_at
            """,
            (
                pipeline_id,
                execution_id,
                node_id,
                status,
                input_hash,
                output_path,
                error_message,
                retry_count,
                started_at,
                finished_at,
            ),
        )
        await self.conn.commit()

    async def get_node_executions(
        self, execution_id: str
    ) -> list[dict[str, Any]]:
        """Fetch all node executions for a given execution run."""
        cursor = await self.conn.execute(
            "SELECT * FROM node_executions WHERE execution_id = ?",
            (execution_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def get_completed_nodes(self, execution_id: str) -> set[str]:
        """Return the set of node IDs that completed successfully."""
        cursor = await self.conn.execute(
            "SELECT node_id FROM node_executions WHERE execution_id = ? AND status = 'success'",
            (execution_id,),
        )
        rows = await cursor.fetchall()
        return {row["node_id"] for row in rows}

    # -- Cache CRUD -----------------------------------------------------------

    async def save_cache_entry(
        self,
        node_id: str,
        input_hash: str,
        output_path: str,
        serialization_format: str = "pickle",
        size_bytes: int = 0,
    ) -> None:
        """Insert or update a cache entry."""
        now = datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            INSERT INTO cache_entries
                (node_id, input_hash, output_path, serialization_format, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id, input_hash) DO UPDATE SET
                output_path=excluded.output_path,
                serialization_format=excluded.serialization_format,
                size_bytes=excluded.size_bytes,
                created_at=excluded.created_at
            """,
            (node_id, input_hash, output_path, serialization_format, size_bytes, now),
        )
        await self.conn.commit()

    async def get_cache_entry(
        self, node_id: str, input_hash: str
    ) -> dict[str, Any] | None:
        """Look up a cache entry by node ID and input hash."""
        cursor = await self.conn.execute(
            "SELECT * FROM cache_entries WHERE node_id = ? AND input_hash = ?",
            (node_id, input_hash),
        )
        row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def delete_cache_entry(self, node_id: str, input_hash: str) -> None:
        """Delete a cache entry."""
        await self.conn.execute(
            "DELETE FROM cache_entries WHERE node_id = ? AND input_hash = ?",
            (node_id, input_hash),
        )
        await self.conn.commit()

    # -- Helpers --------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a sqlite Row to a plain dict."""
        return dict(row)
