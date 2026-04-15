"""Tests for the notification system.

Covers ExecutionEvent, SMTPChannel, WebhookChannel, ChannelRegistry,
resolve_channel, Pipeline.notify_on integration, and DB CRUD.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dagloom.core.node import node
from dagloom.core.pipeline import Pipeline
from dagloom.notifications.base import ExecutionEvent
from dagloom.notifications.email import SMTPChannel
from dagloom.notifications.registry import ChannelRegistry, resolve_channel
from dagloom.notifications.webhook import WebhookChannel
from dagloom.store.db import Database

# ---------------------------------------------------------------------------
# ExecutionEvent tests
# ---------------------------------------------------------------------------


class TestExecutionEvent:
    """Tests for ExecutionEvent dataclass."""

    def test_defaults(self) -> None:
        event = ExecutionEvent(pipeline_name="test")
        assert event.pipeline_name == "test"
        assert event.status == "success"
        assert event.is_success is True
        assert event.finished_at  # auto-populated

    def test_failed_event(self) -> None:
        event = ExecutionEvent(
            pipeline_name="test",
            status="failed",
            error_message="Node X exploded",
            failed_node="X",
        )
        assert event.is_success is False
        assert "X" in event.summary()
        assert "exploded" in event.summary()

    def test_to_dict(self) -> None:
        event = ExecutionEvent(
            pipeline_name="etl",
            execution_id="abc",
            status="success",
            duration_seconds=5.0,
            node_count=3,
        )
        d = event.to_dict()
        assert d["pipeline_name"] == "etl"
        assert d["execution_id"] == "abc"
        assert d["node_count"] == 3

    def test_summary_success(self) -> None:
        event = ExecutionEvent(
            pipeline_name="daily",
            status="success",
            duration_seconds=2.5,
        )
        s = event.summary()
        assert "daily" in s
        assert "success" in s
        assert "2.5s" in s

    def test_summary_failure(self) -> None:
        event = ExecutionEvent(
            pipeline_name="daily",
            status="failed",
            error_message="timeout",
        )
        s = event.summary()
        assert "\u274c" in s
        assert "timeout" in s


# ---------------------------------------------------------------------------
# SMTPChannel tests
# ---------------------------------------------------------------------------


class TestSMTPChannel:
    """Tests for SMTPChannel (mocked SMTP)."""

    @pytest.mark.asyncio
    async def test_send_calls_aiosmtplib(self) -> None:
        channel = SMTPChannel(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
            from_addr="from@test.com",
            to_addrs=["to@test.com"],
        )
        event = ExecutionEvent(
            pipeline_name="test",
            execution_id="e1",
            status="success",
            duration_seconds=1.0,
        )
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await channel.send(event)
            mock_send.assert_called_once()

            # Check the message was built correctly.
            msg = mock_send.call_args.args[0]
            assert "test" in msg["Subject"]
            assert "to@test.com" in msg["To"]

    @pytest.mark.asyncio
    async def test_send_skips_if_no_recipients(self) -> None:
        channel = SMTPChannel(to_addrs=[])
        event = ExecutionEvent(pipeline_name="test")
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await channel.send(event)
            mock_send.assert_not_called()

    def test_build_message_failure(self) -> None:
        channel = SMTPChannel(
            from_addr="from@test.com",
            to_addrs=["to@test.com"],
        )
        event = ExecutionEvent(
            pipeline_name="etl",
            status="failed",
            error_message="Node crashed",
            failed_node="fetch",
        )
        msg = channel._build_message(event)
        assert "FAILED" in msg["Subject"]
        body = msg.get_content()
        assert "Node crashed" in body
        assert "fetch" in body

    def test_repr(self) -> None:
        ch = SMTPChannel(host="smtp.test.com", to_addrs=["a@b.com"])
        assert "smtp.test.com" in repr(ch)


# ---------------------------------------------------------------------------
# WebhookChannel tests
# ---------------------------------------------------------------------------


class TestWebhookChannel:
    """Tests for WebhookChannel (mocked HTTP)."""

    @pytest.mark.asyncio
    async def test_send_generic(self) -> None:
        channel = WebhookChannel(url="https://example.com/hook", format="generic")
        event = ExecutionEvent(
            pipeline_name="test",
            execution_id="e1",
            status="success",
        )
        with patch("dagloom.notifications.webhook.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_response)

            await channel.send(event)
            mock_client.post.assert_called_once()

            payload = mock_client.post.call_args.kwargs["json"]
            assert payload["event"] == "pipeline_execution"
            assert payload["pipeline_name"] == "test"

    def test_format_slack(self) -> None:
        event = ExecutionEvent(
            pipeline_name="daily",
            execution_id="abc",
            status="failed",
            error_message="boom",
            duration_seconds=5.0,
            node_count=3,
        )
        payload = WebhookChannel._format_slack(event)
        assert "blocks" in payload
        assert "attachments" in payload
        # Error block should be included.
        blocks_text = json.dumps(payload["blocks"])
        assert "boom" in blocks_text

    def test_format_wechat_work(self) -> None:
        event = ExecutionEvent(pipeline_name="etl", status="success")
        payload = WebhookChannel._format_wechat_work(event)
        assert payload["msgtype"] == "markdown"
        assert "etl" in payload["markdown"]["content"]

    def test_format_feishu(self) -> None:
        event = ExecutionEvent(
            pipeline_name="etl",
            status="failed",
            error_message="timeout",
        )
        payload = WebhookChannel._format_feishu(event)
        assert payload["msg_type"] == "interactive"
        card_text = json.dumps(payload["card"])
        assert "timeout" in card_text

    def test_repr(self) -> None:
        ch = WebhookChannel(url="https://x.com/hook", format="slack")
        assert "slack" in repr(ch)


# ---------------------------------------------------------------------------
# ChannelRegistry tests
# ---------------------------------------------------------------------------


class TestChannelRegistry:
    """Tests for ChannelRegistry."""

    def test_register_and_get(self) -> None:
        reg = ChannelRegistry()
        ch = WebhookChannel(url="https://test.com")
        reg.register("test", ch)
        assert reg.get("test") is ch

    def test_get_nonexistent(self) -> None:
        reg = ChannelRegistry()
        assert reg.get("nope") is None

    def test_unregister(self) -> None:
        reg = ChannelRegistry()
        ch = WebhookChannel(url="https://test.com")
        reg.register("test", ch)
        reg.unregister("test")
        assert reg.get("test") is None

    def test_list_channels(self) -> None:
        reg = ChannelRegistry()
        ch1 = WebhookChannel(url="https://a.com")
        ch2 = WebhookChannel(url="https://b.com")
        reg.register("a", ch1)
        reg.register("b", ch2)
        channels = reg.list_channels()
        assert len(channels) == 2

    @pytest.mark.asyncio
    async def test_close_all(self) -> None:
        reg = ChannelRegistry()
        ch = WebhookChannel(url="https://test.com")
        reg.register("test", ch)
        await reg.close_all()
        assert len(reg.list_channels()) == 0


# ---------------------------------------------------------------------------
# resolve_channel tests
# ---------------------------------------------------------------------------


class TestResolveChannel:
    """Tests for URI-based channel resolution."""

    def test_email_uri(self) -> None:
        ch = resolve_channel("email://ops@team.com")
        assert isinstance(ch, SMTPChannel)
        assert "ops@team.com" in ch.to_addrs

    def test_webhook_generic_uri(self) -> None:
        ch = resolve_channel("webhook://https://hooks.example.com/abc")
        assert isinstance(ch, WebhookChannel)
        assert ch.url == "https://hooks.example.com/abc"
        assert ch.format == "generic"

    def test_webhook_slack_uri(self) -> None:
        ch = resolve_channel("webhook://https://hooks.slack.com/services/T/B/x?format=slack")
        assert isinstance(ch, WebhookChannel)
        assert ch.format == "slack"

    def test_webhook_wechat_uri(self) -> None:
        ch = resolve_channel(
            "webhook://https://qyapi.weixin.qq.com/cgi-bin/webhook/send?format=wechat_work"
        )
        assert isinstance(ch, WebhookChannel)
        assert ch.format == "wechat_work"

    def test_unsupported_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            resolve_channel("ftp://nope.com")


# ---------------------------------------------------------------------------
# Pipeline.notify_on tests
# ---------------------------------------------------------------------------


class TestPipelineNotifyOn:
    """Tests for Pipeline.notify_on attribute."""

    def test_default_is_none(self) -> None:
        p = Pipeline(name="test")
        assert p.notify_on is None

    def test_notify_on_param(self) -> None:
        p = Pipeline(
            name="test",
            notify_on={"failure": ["email://ops@team.com"]},
        )
        assert p.notify_on == {"failure": ["email://ops@team.com"]}

    def test_notify_on_preserved_in_copy(self) -> None:
        p = Pipeline(
            name="test",
            notify_on={"success": ["webhook://https://hook.com"]},
        )
        p2 = p.copy()
        assert p2.notify_on == p.notify_on

    def test_existing_pipeline_behavior_unchanged(self) -> None:
        @node
        def a(x: int) -> int:
            return x + 1

        @node
        def b(x: int) -> int:
            return x * 2

        pipeline = a >> b
        assert pipeline.notify_on is None
        result = pipeline.run(x=1)
        assert result == 4


# ---------------------------------------------------------------------------
# Executor notification dispatch integration tests
# ---------------------------------------------------------------------------


class TestExecutorNotificationDispatch:
    """Tests for notification dispatch in AsyncExecutor."""

    @pytest.mark.asyncio
    async def test_sends_on_success(self) -> None:
        @node
        def step_a(x: int) -> int:
            return x + 1

        @node
        def step_b(x: int) -> int:
            return x * 2

        pipeline = step_a >> step_b
        pipeline.name = "test"
        pipeline.notify_on = {"success": ["webhook://https://hooks.example.com"]}

        from dagloom.scheduler.executor import AsyncExecutor

        with patch("dagloom.notifications.registry.resolve_channel") as mock_resolve:
            mock_channel = AsyncMock()
            mock_resolve.return_value = mock_channel

            result = await AsyncExecutor(pipeline).execute(x=1)
            assert result == 4

            mock_resolve.assert_called_once_with("webhook://https://hooks.example.com")
            mock_channel.send.assert_called_once()
            event = mock_channel.send.call_args.args[0]
            assert event.status == "success"

    @pytest.mark.asyncio
    async def test_sends_on_failure(self) -> None:
        @node
        def ok_step(x: int) -> int:
            return x + 1

        @node
        def bad_step(x: int) -> int:
            raise RuntimeError("boom")

        pipeline = ok_step >> bad_step
        pipeline.name = "test"
        pipeline.notify_on = {"failed": ["email://ops@team.com"]}

        from dagloom.scheduler.executor import AsyncExecutor, ExecutionError

        with patch("dagloom.notifications.registry.resolve_channel") as mock_resolve:
            mock_channel = AsyncMock()
            mock_resolve.return_value = mock_channel

            with pytest.raises(ExecutionError):
                await AsyncExecutor(pipeline).execute(x=1)

            mock_resolve.assert_called_once_with("email://ops@team.com")
            mock_channel.send.assert_called_once()
            event = mock_channel.send.call_args.args[0]
            assert event.status == "failed"

    @pytest.mark.asyncio
    async def test_no_notification_when_not_configured(self) -> None:
        @node
        def na(x: int) -> int:
            return x + 1

        @node
        def nb(x: int) -> int:
            return x * 2

        pipeline = na >> nb
        pipeline.name = "test"
        # No notify_on set.

        from dagloom.scheduler.executor import AsyncExecutor

        with patch("dagloom.notifications.registry.resolve_channel") as mock_resolve:
            result = await AsyncExecutor(pipeline).execute(x=1)
            assert result == 4
            mock_resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_crash(self) -> None:
        @node
        def nc(x: int) -> int:
            return x + 1

        @node
        def nd(x: int) -> int:
            return x * 2

        pipeline = nc >> nd
        pipeline.name = "test"
        pipeline.notify_on = {"success": ["webhook://https://bad-hook.com"]}

        from dagloom.scheduler.executor import AsyncExecutor

        with patch("dagloom.notifications.registry.resolve_channel") as mock_resolve:
            mock_channel = AsyncMock()
            mock_channel.send.side_effect = RuntimeError("Network error")
            mock_resolve.return_value = mock_channel

            # Should complete successfully despite notification failure.
            result = await AsyncExecutor(pipeline).execute(x=1)
            assert result == 4


# ---------------------------------------------------------------------------
# Database notification channel CRUD tests
# ---------------------------------------------------------------------------


class TestDatabaseNotificationCRUD:
    """Tests for notification channel DB operations."""

    @pytest.fixture
    async def db(self, tmp_path: Path) -> Database:
        db = Database(db_path=tmp_path / "test.db")
        await db.connect()
        yield db
        await db.close()

    @pytest.mark.asyncio
    async def test_save_and_get(self, db: Database) -> None:
        await db.save_notification_channel(
            channel_id="ch1",
            name="slack-alerts",
            channel_type="webhook",
            config={"url": "https://hooks.slack.com/xxx", "format": "slack"},
        )
        result = await db.get_notification_channel("ch1")
        assert result is not None
        assert result["name"] == "slack-alerts"
        assert result["type"] == "webhook"
        config = json.loads(result["config"])
        assert config["format"] == "slack"

    @pytest.mark.asyncio
    async def test_list(self, db: Database) -> None:
        await db.save_notification_channel("c1", "email-ops", "email")
        await db.save_notification_channel("c2", "slack-dev", "webhook")
        channels = await db.list_notification_channels()
        assert len(channels) == 2

    @pytest.mark.asyncio
    async def test_delete(self, db: Database) -> None:
        await db.save_notification_channel("c1", "test", "webhook")
        await db.delete_notification_channel("c1")
        result = await db.get_notification_channel("c1")
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert(self, db: Database) -> None:
        await db.save_notification_channel("c1", "test", "webhook")
        await db.save_notification_channel("c1", "test-updated", "webhook", config={"url": "new"})
        result = await db.get_notification_channel("c1")
        assert result is not None
        assert result["name"] == "test-updated"
