"""Built-in scheduler service for Dagloom pipelines.

Wraps APScheduler's ``AsyncIOScheduler`` to provide cron and interval
scheduling for registered pipelines.  Schedules are persisted to the
Dagloom SQLite database so they survive restarts.

Example::

    scheduler = SchedulerService(db)
    await scheduler.start()

    schedule_id = await scheduler.register(
        pipeline=my_pipeline,
        cron_expr="0 9 * * *",
    )

    await scheduler.stop()
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger

from dagloom.scheduler.triggers import describe_trigger, parse_trigger
from dagloom.store.db import Database

logger = logging.getLogger(__name__)


class ScheduleInfo:
    """Information about a registered schedule.

    Attributes:
        id: Unique schedule identifier.
        pipeline_id: The pipeline this schedule triggers.
        pipeline_name: Human-readable pipeline name.
        cron_expr: The schedule expression (cron or interval shorthand).
        enabled: Whether the schedule is currently active.
        last_run: ISO timestamp of the last execution, or None.
        next_run: ISO timestamp of the next planned execution, or None.
        description: Human-readable description of the schedule.
    """

    def __init__(
        self,
        id: str,
        pipeline_id: str,
        pipeline_name: str,
        cron_expr: str,
        enabled: bool = True,
        last_run: str | None = None,
        next_run: str | None = None,
    ) -> None:
        self.id = id
        self.pipeline_id = pipeline_id
        self.pipeline_name = pipeline_name
        self.cron_expr = cron_expr
        self.enabled = enabled
        self.last_run = last_run
        self.next_run = next_run
        self.description = describe_trigger(cron_expr)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "id": self.id,
            "pipeline_id": self.pipeline_id,
            "pipeline_name": self.pipeline_name,
            "cron_expr": self.cron_expr,
            "enabled": self.enabled,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "description": self.description,
        }


class SchedulerService:
    """Pipeline scheduler backed by APScheduler.

    The scheduler runs in-process with the Dagloom server.  Each
    registered pipeline gets an APScheduler job that triggers
    ``AsyncExecutor.execute()`` on the configured schedule.

    Args:
        db: Database instance for schedule persistence.
        misfire_grace_time: Seconds after the designated run time that
            the job is still allowed to fire (default 60s).
    """

    def __init__(
        self,
        db: Database,
        *,
        misfire_grace_time: int = 60,
    ) -> None:
        self.db = db
        self._scheduler = AsyncIOScheduler(
            job_defaults={
                "misfire_grace_time": misfire_grace_time,
                "coalesce": True,
                "max_instances": 1,
            },
        )
        # In-memory registry: schedule_id -> Pipeline object
        self._pipelines: dict[str, Any] = {}
        self._running = False

    @property
    def running(self) -> bool:
        """Whether the scheduler is currently running."""
        return self._running

    async def start(self) -> None:
        """Start the scheduler and restore persisted schedules."""
        if self._running:
            logger.warning("Scheduler is already running.")
            return

        self._scheduler.start()
        self._running = True
        logger.info("Scheduler started.")

        # Restore persisted schedules.
        schedules = await self.db.list_schedules()
        restored = 0
        for sched in schedules:
            if sched.get("enabled"):
                try:
                    trigger = parse_trigger(sched["cron_expr"])
                    self._add_job(sched["id"], sched["pipeline_id"], trigger)
                    restored += 1
                except Exception:
                    logger.warning(
                        "Failed to restore schedule %s: invalid expression %r",
                        sched["id"],
                        sched.get("cron_expr"),
                    )
        if restored:
            logger.info("Restored %d schedule(s) from database.", restored)

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if not self._running:
            return
        self._scheduler.shutdown(wait=False)
        self._running = False
        self._pipelines.clear()
        logger.info("Scheduler stopped.")

    async def register(
        self,
        pipeline: Any,
        cron_expr: str,
        *,
        pipeline_id: str | None = None,
        enabled: bool = True,
        misfire_policy: str = "skip",
    ) -> str:
        """Register a pipeline for scheduled execution.

        Args:
            pipeline: A ``Pipeline`` object to execute on schedule.
            cron_expr: Cron expression or interval shorthand.
            pipeline_id: Override the pipeline ID (defaults to pipeline.name).
            enabled: Whether to start the schedule immediately.
            misfire_policy: What to do on missed fires ("skip" or "run").

        Returns:
            The schedule ID.

        Raises:
            ValueError: If the cron expression is invalid.
        """
        trigger = parse_trigger(cron_expr)  # Validates the expression.
        pipe_id = pipeline_id or getattr(pipeline, "name", "") or "unnamed"
        schedule_id = uuid.uuid4().hex[:12]

        # Persist to DB.
        await self.db.save_schedule(
            schedule_id=schedule_id,
            pipeline_id=pipe_id,
            cron_expr=cron_expr,
            enabled=enabled,
            misfire_policy=misfire_policy,
        )

        # Store pipeline object in memory for execution.
        self._pipelines[schedule_id] = pipeline

        # Add the APScheduler job if enabled.
        if enabled and self._running:
            self._add_job(schedule_id, pipe_id, trigger)

        logger.info(
            "Registered schedule %s for pipeline %r: %s",
            schedule_id,
            pipe_id,
            describe_trigger(cron_expr),
        )
        return schedule_id

    async def unregister(self, schedule_id: str) -> None:
        """Remove a schedule entirely.

        Args:
            schedule_id: The schedule to remove.
        """
        self._remove_job(schedule_id)
        self._pipelines.pop(schedule_id, None)
        await self.db.delete_schedule(schedule_id)
        logger.info("Unregistered schedule %s.", schedule_id)

    async def pause(self, schedule_id: str) -> None:
        """Pause a schedule (keeps the DB record but stops firing).

        Args:
            schedule_id: The schedule to pause.
        """
        self._remove_job(schedule_id)
        sched = await self.db.get_schedule(schedule_id)
        if sched:
            await self.db.save_schedule(
                schedule_id=schedule_id,
                pipeline_id=sched["pipeline_id"],
                cron_expr=sched["cron_expr"],
                enabled=False,
                misfire_policy=sched.get("misfire_policy", "skip"),
            )
        logger.info("Paused schedule %s.", schedule_id)

    async def resume(self, schedule_id: str) -> None:
        """Resume a paused schedule.

        Args:
            schedule_id: The schedule to resume.
        """
        sched = await self.db.get_schedule(schedule_id)
        if sched is None:
            raise ValueError(f"Schedule {schedule_id!r} not found.")

        trigger = parse_trigger(sched["cron_expr"])
        await self.db.save_schedule(
            schedule_id=schedule_id,
            pipeline_id=sched["pipeline_id"],
            cron_expr=sched["cron_expr"],
            enabled=True,
            misfire_policy=sched.get("misfire_policy", "skip"),
        )

        if self._running:
            self._add_job(schedule_id, sched["pipeline_id"], trigger)
        logger.info("Resumed schedule %s.", schedule_id)

    async def list_schedules(self) -> list[ScheduleInfo]:
        """List all registered schedules.

        Returns:
            A list of ``ScheduleInfo`` objects.
        """
        schedules = await self.db.list_schedules()
        result: list[ScheduleInfo] = []
        for sched in schedules:
            # Try to get next_run from APScheduler job.
            next_run = sched.get("next_run")
            job = self._scheduler.get_job(sched["id"])
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()

            pipeline = await self.db.get_pipeline(sched["pipeline_id"])
            pipeline_name = pipeline["name"] if pipeline else sched["pipeline_id"]

            result.append(
                ScheduleInfo(
                    id=sched["id"],
                    pipeline_id=sched["pipeline_id"],
                    pipeline_name=pipeline_name,
                    cron_expr=sched["cron_expr"],
                    enabled=bool(sched.get("enabled", True)),
                    last_run=sched.get("last_run"),
                    next_run=next_run,
                )
            )
        return result

    def set_pipeline(self, schedule_id: str, pipeline: Any) -> None:
        """Associate a Pipeline object with a schedule (for server use).

        When the server starts and restores schedules from the DB, it needs
        to re-associate the in-memory Pipeline objects so they can be
        executed.

        Args:
            schedule_id: The schedule to associate.
            pipeline: The Pipeline object.
        """
        self._pipelines[schedule_id] = pipeline

    # -- Internal helpers -----------------------------------------------------

    def _add_job(
        self,
        schedule_id: str,
        pipeline_id: str,
        trigger: BaseTrigger,
    ) -> None:
        """Add an APScheduler job for the given schedule."""
        # Remove existing job if any (idempotent re-add).
        self._remove_job(schedule_id)

        self._scheduler.add_job(
            func=self._execute_pipeline,
            trigger=trigger,
            id=schedule_id,
            args=[schedule_id, pipeline_id],
            name=f"pipeline:{pipeline_id}",
            replace_existing=True,
        )

    def _remove_job(self, schedule_id: str) -> None:
        """Remove an APScheduler job if it exists."""
        import contextlib

        with contextlib.suppress(Exception):
            self._scheduler.remove_job(schedule_id)

    async def _execute_pipeline(
        self,
        schedule_id: str,
        pipeline_id: str,
    ) -> None:
        """Callback invoked by APScheduler to execute a pipeline.

        This is an async function that APScheduler calls on the event
        loop.  It delegates to ``AsyncExecutor`` for actual execution.
        """
        from dagloom.scheduler.executor import AsyncExecutor

        pipeline = self._pipelines.get(schedule_id)
        if pipeline is None:
            logger.warning(
                "Schedule %s fired but no Pipeline object registered for %r. Skipping execution.",
                schedule_id,
                pipeline_id,
            )
            return

        now = datetime.now(UTC).isoformat()

        # Update last_run in DB.
        job = self._scheduler.get_job(schedule_id)
        next_run_str = None
        if job and job.next_run_time:
            next_run_str = job.next_run_time.isoformat()
        await self.db.update_schedule_last_run(schedule_id, now, next_run_str)

        logger.info(
            "Scheduled execution of pipeline %r (schedule %s).",
            pipeline_id,
            schedule_id,
        )

        try:
            executor = AsyncExecutor(pipeline)
            await executor.execute()
            logger.info(
                "Scheduled execution of pipeline %r completed successfully.",
                pipeline_id,
            )
        except Exception as exc:
            logger.error(
                "Scheduled execution of pipeline %r failed: %s",
                pipeline_id,
                exc,
            )
