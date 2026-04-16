"""SQLite storage layer for Dagloom.

Provides an async wrapper around SQLite via aiosqlite, managing
pipeline definitions, execution records, node execution states,
and cache metadata.  Uses WAL mode for improved concurrent performance.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
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

CREATE TABLE IF NOT EXISTS schedules (
    id             TEXT PRIMARY KEY,
    pipeline_id    TEXT NOT NULL,
    cron_expr      TEXT NOT NULL,
    enabled        INTEGER DEFAULT 1,
    last_run       TEXT,
    next_run       TEXT,
    misfire_policy TEXT DEFAULT 'skip',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
);

CREATE TABLE IF NOT EXISTS dagloom_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_channels (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    type       TEXT NOT NULL,
    config     TEXT DEFAULT '{}',
    enabled    INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS secrets (
    key             TEXT PRIMARY KEY,
    encrypted_value TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS node_metrics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id   TEXT NOT NULL,
    execution_id  TEXT NOT NULL,
    node_id       TEXT NOT NULL,
    wall_time_ms  REAL NOT NULL,
    outcome       TEXT NOT NULL,
    retry_count   INTEGER DEFAULT 0,
    error_message TEXT,
    recorded_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_node_metrics_pipeline
    ON node_metrics(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_node_metrics_node
    ON node_metrics(node_id);
CREATE INDEX IF NOT EXISTS idx_node_metrics_recorded
    ON node_metrics(recorded_at);

CREATE TABLE IF NOT EXISTS pipeline_versions (
    version_hash  TEXT PRIMARY KEY,
    pipeline_id   TEXT NOT NULL,
    code_snapshot  TEXT NOT NULL,
    node_names    TEXT DEFAULT '[]',
    edges         TEXT DEFAULT '[]',
    description   TEXT DEFAULT '',
    created_at    TEXT NOT NULL,
    FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_versions_pipeline
    ON pipeline_versions(pipeline_id);
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
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO pipelines (id, name, description, node_names,
                edges, source_file, created_at, updated_at)
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
        cursor = await self.conn.execute("SELECT * FROM pipelines WHERE id = ?", (pipeline_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    async def list_pipelines(self) -> list[dict[str, Any]]:
        """List all pipelines."""
        cursor = await self.conn.execute("SELECT * FROM pipelines ORDER BY updated_at DESC")
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
            INSERT INTO executions (id, pipeline_id, status, started_at,
                finished_at, error_message, metadata)
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
        cursor = await self.conn.execute("SELECT * FROM executions WHERE id = ?", (execution_id,))
        row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def get_latest_execution(
        self,
        pipeline_id: str,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        """Fetch the most recent execution for a pipeline.

        Args:
            pipeline_id: The pipeline whose executions to query.
            status: If provided, filter by this status (e.g. ``"failed"``).

        Returns:
            A dict representing the execution record, or ``None``.
        """
        if status:
            cursor = await self.conn.execute(
                "SELECT * FROM executions WHERE pipeline_id = ? AND status = ? "
                "ORDER BY started_at DESC LIMIT 1",
                (pipeline_id, status),
            )
        else:
            cursor = await self.conn.execute(
                "SELECT * FROM executions WHERE pipeline_id = ? ORDER BY started_at DESC LIMIT 1",
                (pipeline_id,),
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

    async def get_node_executions(self, execution_id: str) -> list[dict[str, Any]]:
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

    # -- Schedule CRUD --------------------------------------------------------

    async def save_schedule(
        self,
        schedule_id: str,
        pipeline_id: str,
        cron_expr: str,
        enabled: bool = True,
        misfire_policy: str = "skip",
        next_run: str | None = None,
    ) -> None:
        """Insert or update a schedule."""
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO schedules (id, pipeline_id, cron_expr, enabled,
                misfire_policy, next_run, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                cron_expr=excluded.cron_expr,
                enabled=excluded.enabled,
                misfire_policy=excluded.misfire_policy,
                next_run=excluded.next_run,
                updated_at=excluded.updated_at
            """,
            (
                schedule_id,
                pipeline_id,
                cron_expr,
                int(enabled),
                misfire_policy,
                next_run,
                now,
                now,
            ),
        )
        await self.conn.commit()

    async def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        """Fetch a schedule by ID."""
        cursor = await self.conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
        row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def get_schedule_by_pipeline(self, pipeline_id: str) -> dict[str, Any] | None:
        """Fetch the schedule for a pipeline."""
        cursor = await self.conn.execute(
            "SELECT * FROM schedules WHERE pipeline_id = ? LIMIT 1", (pipeline_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def list_schedules(self) -> list[dict[str, Any]]:
        """List all schedules."""
        cursor = await self.conn.execute("SELECT * FROM schedules ORDER BY updated_at DESC")
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def delete_schedule(self, schedule_id: str) -> None:
        """Delete a schedule."""
        await self.conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        await self.conn.commit()

    async def update_schedule_last_run(
        self,
        schedule_id: str,
        last_run: str,
        next_run: str | None = None,
    ) -> None:
        """Update the last_run and next_run timestamps for a schedule."""
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            UPDATE schedules
            SET last_run = ?, next_run = ?, updated_at = ?
            WHERE id = ?
            """,
            (last_run, next_run, now, schedule_id),
        )
        await self.conn.commit()

    # -- Schema Version -------------------------------------------------------

    async def get_schema_version(self) -> int:
        """Get the current schema version (0 if not set)."""
        try:
            cursor = await self.conn.execute(
                "SELECT value FROM dagloom_meta WHERE key = 'schema_version'"
            )
            row = await cursor.fetchone()
            return int(row["value"]) if row else 0
        except Exception:
            return 0

    async def set_schema_version(self, version: int) -> None:
        """Set the schema version."""
        await self.conn.execute(
            """
            INSERT INTO dagloom_meta (key, value)
            VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(version),),
        )
        await self.conn.commit()

    # -- Notification Channel CRUD --------------------------------------------

    async def save_notification_channel(
        self,
        channel_id: str,
        name: str,
        channel_type: str,
        config: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> None:
        """Insert or update a notification channel."""
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO notification_channels (id, name, type, config,
                enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                type=excluded.type,
                config=excluded.config,
                enabled=excluded.enabled,
                updated_at=excluded.updated_at
            """,
            (
                channel_id,
                name,
                channel_type,
                json.dumps(config or {}),
                int(enabled),
                now,
                now,
            ),
        )
        await self.conn.commit()

    async def get_notification_channel(self, channel_id: str) -> dict[str, Any] | None:
        """Fetch a notification channel by ID."""
        cursor = await self.conn.execute(
            "SELECT * FROM notification_channels WHERE id = ?", (channel_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def list_notification_channels(self) -> list[dict[str, Any]]:
        """List all notification channels."""
        cursor = await self.conn.execute(
            "SELECT * FROM notification_channels ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def delete_notification_channel(self, channel_id: str) -> None:
        """Delete a notification channel."""
        await self.conn.execute("DELETE FROM notification_channels WHERE id = ?", (channel_id,))
        await self.conn.commit()

    # -- Secrets CRUD ---------------------------------------------------------

    async def save_secret(self, key: str, encrypted_value: str) -> None:
        """Insert or update an encrypted secret."""
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO secrets (key, encrypted_value, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                encrypted_value=excluded.encrypted_value,
                updated_at=excluded.updated_at
            """,
            (key, encrypted_value, now, now),
        )
        await self.conn.commit()

    async def get_secret(self, key: str) -> dict[str, Any] | None:
        """Fetch a secret by key (returns encrypted value)."""
        cursor = await self.conn.execute("SELECT * FROM secrets WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def list_secrets(self) -> list[dict[str, Any]]:
        """List all secrets (key and timestamps only, no values)."""
        cursor = await self.conn.execute(
            "SELECT key, created_at, updated_at FROM secrets ORDER BY key"
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def delete_secret(self, key: str) -> None:
        """Delete a secret by key."""
        await self.conn.execute("DELETE FROM secrets WHERE key = ?", (key,))
        await self.conn.commit()

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
        now = datetime.now(UTC).isoformat()
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

    async def get_cache_entry(self, node_id: str, input_hash: str) -> dict[str, Any] | None:
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

    async def delete_cache_entries_for_node(self, node_id: str) -> int:
        """Delete **all** cache entries for a given node.

        Args:
            node_id: The node whose cache entries to delete.

        Returns:
            The number of deleted rows.
        """
        cursor = await self.conn.execute(
            "DELETE FROM cache_entries WHERE node_id = ?",
            (node_id,),
        )
        await self.conn.commit()
        return cursor.rowcount

    async def get_cache_entries_for_node(self, node_id: str) -> list[dict[str, Any]]:
        """Fetch all cache entries for a given node.

        Args:
            node_id: The node whose cache entries to fetch.

        Returns:
            A list of cache entry dicts.
        """
        cursor = await self.conn.execute(
            "SELECT * FROM cache_entries WHERE node_id = ?",
            (node_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    # -- Pipeline Version CRUD --------------------------------------------------

    async def save_pipeline_version(
        self,
        version_hash: str,
        pipeline_id: str,
        code_snapshot: str,
        node_names: list[str] | None = None,
        edges: list[tuple[str, str]] | None = None,
        description: str = "",
    ) -> None:
        """Save a pipeline version snapshot (idempotent — skips if hash exists)."""
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT OR IGNORE INTO pipeline_versions
                (version_hash, pipeline_id, code_snapshot, node_names,
                 edges, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_hash,
                pipeline_id,
                code_snapshot,
                json.dumps(node_names or []),
                json.dumps(edges or []),
                description,
                now,
            ),
        )
        await self.conn.commit()

    async def get_pipeline_version(self, version_hash: str) -> dict[str, Any] | None:
        """Fetch a pipeline version by its hash."""
        cursor = await self.conn.execute(
            "SELECT * FROM pipeline_versions WHERE version_hash = ?",
            (version_hash,),
        )
        row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def list_pipeline_versions(
        self,
        pipeline_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List version history for a pipeline (newest first)."""
        cursor = await self.conn.execute(
            "SELECT * FROM pipeline_versions WHERE pipeline_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (pipeline_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def delete_pipeline_version(self, version_hash: str) -> None:
        """Delete a pipeline version."""
        await self.conn.execute(
            "DELETE FROM pipeline_versions WHERE version_hash = ?",
            (version_hash,),
        )
        await self.conn.commit()

    # -- Node Metrics CRUD -----------------------------------------------------

    async def save_node_metric(
        self,
        pipeline_id: str,
        execution_id: str,
        node_id: str,
        wall_time_ms: float,
        outcome: str,
        retry_count: int = 0,
        error_message: str | None = None,
    ) -> None:
        """Record a node execution metric."""
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO node_metrics
                (pipeline_id, execution_id, node_id, wall_time_ms,
                 outcome, retry_count, error_message, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pipeline_id,
                execution_id,
                node_id,
                wall_time_ms,
                outcome,
                retry_count,
                error_message,
                now,
            ),
        )
        await self.conn.commit()

    async def get_node_metrics(
        self,
        node_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch recent metrics for a specific node.

        Args:
            node_id: The node to query.
            limit: Maximum rows to return.

        Returns:
            List of metric dicts ordered by most recent first.
        """
        cursor = await self.conn.execute(
            "SELECT * FROM node_metrics WHERE node_id = ? ORDER BY recorded_at DESC LIMIT ?",
            (node_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def get_pipeline_metrics(
        self,
        pipeline_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch recent metrics for all nodes in a pipeline.

        Args:
            pipeline_id: The pipeline to query.
            limit: Maximum rows to return.

        Returns:
            List of metric dicts ordered by most recent first.
        """
        cursor = await self.conn.execute(
            "SELECT * FROM node_metrics WHERE pipeline_id = ? ORDER BY recorded_at DESC LIMIT ?",
            (pipeline_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def get_execution_history(
        self,
        pipeline_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch execution history with summary stats.

        Args:
            pipeline_id: The pipeline to query.
            limit: Maximum executions to return.

        Returns:
            List of execution dicts with node metrics attached.
        """
        cursor = await self.conn.execute(
            "SELECT * FROM executions WHERE pipeline_id = ? ORDER BY started_at DESC LIMIT ?",
            (pipeline_id, limit),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            execution = self._row_to_dict(row)
            # Attach per-node metrics for this execution.
            metrics_cursor = await self.conn.execute(
                "SELECT node_id, wall_time_ms, outcome, retry_count, error_message "
                "FROM node_metrics WHERE execution_id = ? ORDER BY recorded_at",
                (execution["id"],),
            )
            metrics_rows = await metrics_cursor.fetchall()
            execution["node_metrics"] = [self._row_to_dict(m) for m in metrics_rows]
            results.append(execution)
        return results

    async def get_node_stats(
        self,
        pipeline_id: str,
    ) -> list[dict[str, Any]]:
        """Compute aggregate stats per node for a pipeline.

        Returns:
            List of dicts with node_id, total_runs, success_count,
            failure_count, avg_ms, p50_ms, p95_ms.
        """
        cursor = await self.conn.execute(
            """
            SELECT
                node_id,
                COUNT(*)                             AS total_runs,
                SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS success_count,
                SUM(CASE WHEN outcome='failed'  THEN 1 ELSE 0 END) AS failure_count,
                AVG(wall_time_ms)                    AS avg_ms,
                MIN(wall_time_ms)                    AS min_ms,
                MAX(wall_time_ms)                    AS max_ms
            FROM node_metrics
            WHERE pipeline_id = ?
            GROUP BY node_id
            ORDER BY node_id
            """,
            (pipeline_id,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = self._row_to_dict(row)
            # Compute percentiles from raw data.
            pcursor = await self.conn.execute(
                "SELECT wall_time_ms FROM node_metrics "
                "WHERE pipeline_id = ? AND node_id = ? "
                "ORDER BY wall_time_ms",
                (pipeline_id, d["node_id"]),
            )
            times = [r["wall_time_ms"] for r in await pcursor.fetchall()]
            n = len(times)
            d["p50_ms"] = times[n // 2] if n > 0 else 0.0
            d["p95_ms"] = times[int(n * 0.95)] if n > 0 else 0.0
            results.append(d)
        return results

    # -- Helpers --------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a sqlite Row to a plain dict."""
        return dict(row)
