"""HTTP webhook notification channel.

Sends pipeline execution results as JSON POST requests.  Includes
built-in formatters for Slack (Block Kit), WeChat Work, Feishu,
and generic JSON.

Example::

    channel = WebhookChannel(
        url="https://hooks.slack.com/services/T.../B.../xxx",
        format="slack",
    )
    await channel.send(event)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from dagloom.notifications.base import ExecutionEvent, NotificationChannel

logger = logging.getLogger(__name__)


class WebhookChannel(NotificationChannel):
    """HTTP webhook notification channel.

    Args:
        url: The webhook endpoint URL.
        format: Payload format — ``"generic"``, ``"slack"``,
            ``"wechat_work"``, or ``"feishu"``.
        headers: Extra HTTP headers to include.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        *,
        url: str,
        format: str = "generic",
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.url = url
        self.format = format
        self.headers = headers or {}
        self.timeout = timeout

    async def send(self, event: ExecutionEvent) -> None:
        """Send a webhook POST request.

        Args:
            event: The execution event to report.

        Raises:
            httpx.HTTPStatusError: If the server returns a non-2xx status.
        """
        payload = self._format_payload(event)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.url,
                json=payload,
                headers={"Content-Type": "application/json", **self.headers},
            )
            resp.raise_for_status()

        logger.info(
            "Webhook sent to %s for pipeline '%s' (%s).",
            self.url,
            event.pipeline_name,
            event.status,
        )

    def _format_payload(self, event: ExecutionEvent) -> dict[str, Any]:
        """Format the payload based on the configured format."""
        formatters = {
            "generic": self._format_generic,
            "slack": self._format_slack,
            "wechat_work": self._format_wechat_work,
            "feishu": self._format_feishu,
        }
        formatter = formatters.get(self.format, self._format_generic)
        return formatter(event)

    @staticmethod
    def _format_generic(event: ExecutionEvent) -> dict[str, Any]:
        """Generic JSON payload — includes all event fields."""
        return {
            "event": "pipeline_execution",
            **event.to_dict(),
        }

    @staticmethod
    def _format_slack(event: ExecutionEvent) -> dict[str, Any]:
        """Slack Block Kit payload."""
        icon = ":white_check_mark:" if event.is_success else ":x:"
        status_text = event.status.upper()
        color = "#36a64f" if event.is_success else "#dc3545"

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{icon} Pipeline: {event.pipeline_name}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Status:*\n{status_text}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Duration:*\n{event.duration_seconds:.1f}s",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Execution ID:*\n`{event.execution_id}`",
                    },
                    {"type": "mrkdwn", "text": f"*Nodes:*\n{event.node_count}"},
                ],
            },
        ]

        if event.error_message:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Error:*\n```{event.error_message}```",
                    },
                }
            )

        return {
            "blocks": blocks,
            "attachments": [{"color": color, "text": ""}],
        }

    @staticmethod
    def _format_wechat_work(event: ExecutionEvent) -> dict[str, Any]:
        """WeChat Work (WeCom) markdown message."""
        icon = "\u2705" if event.is_success else "\u274c"
        lines = [
            f"## {icon} Pipeline: {event.pipeline_name}",
            f"> Status: **{event.status.upper()}**",
            f"> Duration: {event.duration_seconds:.1f}s",
            f"> Execution: `{event.execution_id}`",
            f"> Nodes: {event.node_count}",
        ]
        if event.error_message:
            lines.append(f"> Error: {event.error_message}")

        return {
            "msgtype": "markdown",
            "markdown": {"content": "\n".join(lines)},
        }

    @staticmethod
    def _format_feishu(event: ExecutionEvent) -> dict[str, Any]:
        """Feishu (Lark) interactive card message."""
        icon = "\u2705" if event.is_success else "\u274c"
        color = "green" if event.is_success else "red"

        elements: list[dict[str, Any]] = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**Status:** {event.status.upper()}\n"
                        f"**Duration:** {event.duration_seconds:.1f}s\n"
                        f"**Execution ID:** `{event.execution_id}`\n"
                        f"**Nodes:** {event.node_count}"
                    ),
                },
            },
        ]

        if event.error_message:
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**Error:**\n```\n{event.error_message}\n```",
                    },
                }
            )

        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"{icon} Pipeline: {event.pipeline_name}",
                    },
                    "template": color,
                },
                "elements": elements,
            },
        }

    def __repr__(self) -> str:
        return f"WebhookChannel(url={self.url!r}, format={self.format!r})"
