"""Tests for the built-in scheduler system.

Covers trigger parsing, SchedulerService lifecycle, schedule CRUD,
and integration with the Pipeline class.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dagloom.core.node import node
from dagloom.core.pipeline import Pipeline
from dagloom.scheduler.triggers import (
    describe_trigger,
    parse_trigger,
    validate_expression,
)
from dagloom.store.db import Database

# ---------------------------------------------------------------------------
# Trigger parsing tests
# ---------------------------------------------------------------------------


class TestParseTrigger:
    """Tests for parse_trigger()."""

    def test_cron_expression_5_fields(self) -> None:
        trigger = parse_trigger("0 9 * * *")
        assert trigger is not None
        # CronTrigger should have been returned.
        from apscheduler.triggers.cron import CronTrigger

        assert isinstance(trigger, CronTrigger)

    def test_cron_expression_with_ranges(self) -> None:
        trigger = parse_trigger("*/5 * * * 1-5")
        from apscheduler.triggers.cron import CronTrigger

        assert isinstance(trigger, CronTrigger)

    def test_interval_every_minutes(self) -> None:
        trigger = parse_trigger("every 30m")
        from apscheduler.triggers.interval import IntervalTrigger

        assert isinstance(trigger, IntervalTrigger)

    def test_interval_every_hours(self) -> None:
        trigger = parse_trigger("every 2h")
        from apscheduler.triggers.interval import IntervalTrigger

        assert isinstance(trigger, IntervalTrigger)

    def test_interval_every_days(self) -> None:
        trigger = parse_trigger("every 1d")
        from apscheduler.triggers.interval import IntervalTrigger

        assert isinstance(trigger, IntervalTrigger)

    def test_interval_every_seconds(self) -> None:
        trigger = parse_trigger("every 10s")
        from apscheduler.triggers.interval import IntervalTrigger

        assert isinstance(trigger, IntervalTrigger)

    def test_interval_verbose_units(self) -> None:
        trigger = parse_trigger("every 5 minutes")
        from apscheduler.triggers.interval import IntervalTrigger

        assert isinstance(trigger, IntervalTrigger)

    def test_interval_case_insensitive(self) -> None:
        trigger = parse_trigger("Every 3H")
        from apscheduler.triggers.interval import IntervalTrigger

        assert isinstance(trigger, IntervalTrigger)

    def test_invalid_expression_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_trigger("not a valid expression")

    def test_too_few_cron_fields_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_trigger("0 9 *")

    def test_too_many_cron_fields_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_trigger("0 9 * * * *")

    def test_whitespace_is_stripped(self) -> None:
        trigger = parse_trigger("  0 9 * * *  ")
        from apscheduler.triggers.cron import CronTrigger

        assert isinstance(trigger, CronTrigger)


class TestDescribeTrigger:
    """Tests for describe_trigger()."""

    def test_cron_description(self) -> None:
        desc = describe_trigger("0 9 * * *")
        assert "Cron" in desc
        assert "0 9 * * *" in desc

    def test_interval_description(self) -> None:
        desc = describe_trigger("every 30m")
        assert "30" in desc
        assert "minutes" in desc

    def test_unknown_expression(self) -> None:
        desc = describe_trigger("unknown")
        assert desc == "unknown"


class TestValidateExpression:
    """Tests for validate_expression()."""

    def test_valid_cron(self) -> None:
        assert validate_expression("0 9 * * *") is True

    def test_valid_interval(self) -> None:
        assert validate_expression("every 5m") is True

    def test_invalid_returns_false(self) -> None:
        assert validate_expression("not valid") is False


# ---------------------------------------------------------------------------
# Pipeline schedule parameter tests
# ---------------------------------------------------------------------------


class TestPipelineSchedule:
    """Tests for the Pipeline.schedule attribute."""

    def test_default_schedule_is_none(self) -> None:
        p = Pipeline(name="test")
        assert p.schedule is None

    def test_schedule_param(self) -> None:
        p = Pipeline(name="test", schedule="0 9 * * *")
        assert p.schedule == "0 9 * * *"

    def test_schedule_preserved_in_copy(self) -> None:
        p = Pipeline(name="test", schedule="every 30m")
        p2 = p.copy()
        assert p2.schedule == "every 30m"

    def test_schedule_settable_after_init(self) -> None:
        p = Pipeline(name="test")
        p.schedule = "0 */2 * * *"
        assert p.schedule == "0 */2 * * *"

    def test_existing_pipeline_behavior_unchanged(self) -> None:
        """Existing pipelines without schedule= still work."""

        @node
        def a(x: int) -> int:
            return x + 1

        @node
        def b(x: int) -> int:
            return x * 2

        pipeline = a >> b
        assert pipeline.schedule is None
        result = pipeline.run(x=1)
        assert result == 4


# ---------------------------------------------------------------------------
# Database schedule CRUD tests
# ---------------------------------------------------------------------------


class TestDatabaseScheduleCRUD:
    """Tests for schedule-related database operations."""

    @pytest.fixture
    async def db(self, tmp_path: Path) -> Database:
        db = Database(db_path=tmp_path / "test.db")
        await db.connect()
        # Create prerequisite pipeline records for FK constraints.
        await db.save_pipeline("p1", "Pipeline 1")
        await db.save_pipeline("p2", "Pipeline 2")
        await db.save_pipeline("pipe1", "Pipe 1")
        yield db
        await db.close()

    @pytest.mark.asyncio
    async def test_save_and_get_schedule(self, db: Database) -> None:
        await db.save_schedule(
            schedule_id="sched1",
            pipeline_id="pipe1",
            cron_expr="0 9 * * *",
        )
        result = await db.get_schedule("sched1")
        assert result is not None
        assert result["pipeline_id"] == "pipe1"
        assert result["cron_expr"] == "0 9 * * *"
        assert result["enabled"] == 1

    @pytest.mark.asyncio
    async def test_get_schedule_by_pipeline(self, db: Database) -> None:
        await db.save_schedule(
            schedule_id="sched1",
            pipeline_id="pipe1",
            cron_expr="0 9 * * *",
        )
        result = await db.get_schedule_by_pipeline("pipe1")
        assert result is not None
        assert result["id"] == "sched1"

    @pytest.mark.asyncio
    async def test_list_schedules(self, db: Database) -> None:
        await db.save_schedule("s1", "p1", "0 9 * * *")
        await db.save_schedule("s2", "p2", "every 30m")
        schedules = await db.list_schedules()
        assert len(schedules) == 2

    @pytest.mark.asyncio
    async def test_delete_schedule(self, db: Database) -> None:
        await db.save_schedule("s1", "p1", "0 9 * * *")
        await db.delete_schedule("s1")
        result = await db.get_schedule("s1")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_schedule_last_run(self, db: Database) -> None:
        await db.save_schedule("s1", "p1", "0 9 * * *")
        now = datetime.now(UTC).isoformat()
        await db.update_schedule_last_run("s1", now, "2026-04-15T09:00:00")
        result = await db.get_schedule("s1")
        assert result is not None
        assert result["last_run"] == now
        assert result["next_run"] == "2026-04-15T09:00:00"

    @pytest.mark.asyncio
    async def test_schema_version(self, db: Database) -> None:
        version = await db.get_schema_version()
        assert version == 0
        await db.set_schema_version(1)
        version = await db.get_schema_version()
        assert version == 1

    @pytest.mark.asyncio
    async def test_get_nonexistent_schedule(self, db: Database) -> None:
        result = await db.get_schedule("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_schedule_upsert(self, db: Database) -> None:
        await db.save_schedule("s1", "p1", "0 9 * * *")
        await db.save_schedule("s1", "p1", "0 10 * * *")
        result = await db.get_schedule("s1")
        assert result is not None
        assert result["cron_expr"] == "0 10 * * *"


# ---------------------------------------------------------------------------
# SchedulerService tests
# ---------------------------------------------------------------------------


class TestSchedulerService:
    """Tests for SchedulerService."""

    @pytest.fixture
    async def db(self, tmp_path: Path) -> Database:
        db = Database(db_path=tmp_path / "test.db")
        await db.connect()
        # Pre-create the pipeline record for FK constraints.
        await db.save_pipeline("test_pipeline", "test_pipeline")
        yield db
        await db.close()

    @pytest.fixture
    def sample_pipeline(self) -> Pipeline:
        @node
        def step_a(x: int = 0) -> int:
            return x + 1

        @node
        def step_b(x: int) -> int:
            return x * 2

        pipeline = step_a >> step_b
        pipeline.name = "test_pipeline"
        return pipeline

    @pytest.mark.asyncio
    async def test_start_and_stop(self, db: Database) -> None:
        from dagloom.scheduler.scheduler import SchedulerService

        svc = SchedulerService(db)
        assert not svc.running

        await svc.start()
        assert svc.running

        await svc.stop()
        assert not svc.running

    @pytest.mark.asyncio
    async def test_register_and_list(
        self, db: Database, sample_pipeline: Pipeline
    ) -> None:
        from dagloom.scheduler.scheduler import SchedulerService

        svc = SchedulerService(db)
        await svc.start()

        schedule_id = await svc.register(
            pipeline=sample_pipeline,
            cron_expr="0 9 * * *",
        )
        assert schedule_id is not None

        schedules = await svc.list_schedules()
        assert len(schedules) == 1
        assert schedules[0].cron_expr == "0 9 * * *"
        assert schedules[0].pipeline_id == "test_pipeline"

        await svc.stop()

    @pytest.mark.asyncio
    async def test_unregister(
        self, db: Database, sample_pipeline: Pipeline
    ) -> None:
        from dagloom.scheduler.scheduler import SchedulerService

        svc = SchedulerService(db)
        await svc.start()

        schedule_id = await svc.register(
            pipeline=sample_pipeline,
            cron_expr="every 5m",
        )
        await svc.unregister(schedule_id)

        schedules = await svc.list_schedules()
        assert len(schedules) == 0

        await svc.stop()

    @pytest.mark.asyncio
    async def test_pause_and_resume(
        self, db: Database, sample_pipeline: Pipeline
    ) -> None:
        from dagloom.scheduler.scheduler import SchedulerService

        svc = SchedulerService(db)
        await svc.start()

        schedule_id = await svc.register(
            pipeline=sample_pipeline,
            cron_expr="0 9 * * *",
        )

        await svc.pause(schedule_id)
        schedules = await svc.list_schedules()
        assert schedules[0].enabled is False

        await svc.resume(schedule_id)
        schedules = await svc.list_schedules()
        assert schedules[0].enabled is True

        await svc.stop()

    @pytest.mark.asyncio
    async def test_register_invalid_expression_raises(
        self, db: Database, sample_pipeline: Pipeline
    ) -> None:
        from dagloom.scheduler.scheduler import SchedulerService

        svc = SchedulerService(db)
        await svc.start()

        with pytest.raises(ValueError, match="Cannot parse"):
            await svc.register(
                pipeline=sample_pipeline,
                cron_expr="not valid",
            )

        await svc.stop()

    @pytest.mark.asyncio
    async def test_schedule_info_to_dict(
        self, db: Database, sample_pipeline: Pipeline
    ) -> None:
        from dagloom.scheduler.scheduler import SchedulerService

        svc = SchedulerService(db)
        await svc.start()

        # First save the pipeline to DB so list_schedules can find it.
        await db.save_pipeline(
            pipeline_id="test_pipeline",
            name="test_pipeline",
        )

        await svc.register(
            pipeline=sample_pipeline,
            cron_expr="0 9 * * *",
        )

        schedules = await svc.list_schedules()
        info_dict = schedules[0].to_dict()
        assert "id" in info_dict
        assert "pipeline_id" in info_dict
        assert "cron_expr" in info_dict
        assert "description" in info_dict

        await svc.stop()

    @pytest.mark.asyncio
    async def test_scheduler_restores_on_start(
        self, db: Database, sample_pipeline: Pipeline
    ) -> None:
        """Schedules persisted in DB are restored when scheduler starts."""
        from dagloom.scheduler.scheduler import SchedulerService

        # Register a schedule.
        svc1 = SchedulerService(db)
        await svc1.start()
        schedule_id = await svc1.register(
            pipeline=sample_pipeline,
            cron_expr="0 9 * * *",
        )
        await svc1.stop()

        # New scheduler instance should restore it.
        svc2 = SchedulerService(db)
        await svc2.start()
        schedules = await svc2.list_schedules()
        assert len(schedules) == 1
        assert schedules[0].id == schedule_id

        await svc2.stop()

    @pytest.mark.asyncio
    async def test_double_start_warns(self, db: Database) -> None:
        from dagloom.scheduler.scheduler import SchedulerService

        svc = SchedulerService(db)
        await svc.start()
        await svc.start()  # Should not raise, just warn.
        assert svc.running
        await svc.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, db: Database) -> None:
        from dagloom.scheduler.scheduler import SchedulerService

        svc = SchedulerService(db)
        await svc.stop()  # Should not raise.
        assert not svc.running
