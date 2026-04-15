"""Notification channel registry and URI-based resolution.

Supports creating channels from URI strings like:

- ``email://ops@team.com`` — SMTP email
- ``webhook://https://hooks.slack.com/...?format=slack`` — Webhook
- ``webhook://https://qyapi.weixin.qq.com/...?format=wechat_work`` — WeChat Work

Example::

    channel = resolve_channel("webhook://https://hooks.slack.com/xxx?format=slack")
    await channel.send(event)
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

from dagloom.notifications.base import NotificationChannel
from dagloom.notifications.email import SMTPChannel
from dagloom.notifications.webhook import WebhookChannel

logger = logging.getLogger(__name__)


class ChannelRegistry:
    """Registry of named notification channel instances.

    Allows channels to be registered by name and looked up later
    (e.g. from ``Pipeline.notify_on`` configuration).
    """

    def __init__(self) -> None:
        self._channels: dict[str, NotificationChannel] = {}

    def register(self, name: str, channel: NotificationChannel) -> None:
        """Register a channel by name.

        Args:
            name: Unique channel name (e.g. ``"slack-alerts"``).
            channel: The channel instance.
        """
        self._channels[name] = channel

    def get(self, name: str) -> NotificationChannel | None:
        """Look up a channel by name."""
        return self._channels.get(name)

    def unregister(self, name: str) -> None:
        """Remove a channel by name."""
        self._channels.pop(name, None)

    def list_channels(self) -> dict[str, NotificationChannel]:
        """Return all registered channels."""
        return dict(self._channels)

    async def close_all(self) -> None:
        """Close all registered channels."""
        for channel in self._channels.values():
            try:
                await channel.close()
            except Exception:
                logger.warning("Failed to close channel %s.", channel)
        self._channels.clear()


def resolve_channel(uri: str, **overrides: Any) -> NotificationChannel:
    """Create a notification channel from a URI string.

    URI schemes:

    - ``email://recipient@example.com`` — Creates an ``SMTPChannel``.
      SMTP config (host, port, username, password) must be passed
      via ``**overrides`` or environment variables.
    - ``webhook://https://hooks.slack.com/...?format=slack`` — Creates
      a ``WebhookChannel``.  The URL after ``webhook://`` is the
      endpoint, query params configure the channel.

    Args:
        uri: Channel URI string.
        **overrides: Additional keyword arguments merged into the
            channel constructor.

    Returns:
        A configured ``NotificationChannel`` instance.

    Raises:
        ValueError: If the URI scheme is unsupported.
    """
    if uri.startswith("email://"):
        addr = uri[len("email://") :]
        params: dict[str, Any] = {"to_addrs": [addr]}
        params.update(overrides)
        return SMTPChannel(**params)

    if uri.startswith("webhook://"):
        raw_url = uri[len("webhook://") :]
        parsed = urlparse(raw_url)

        # Extract format from query params if present.
        qs = parse_qs(parsed.query)
        fmt = qs.get("format", ["generic"])[0]

        # Rebuild URL without our custom query params.
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        params = {"url": clean_url, "format": fmt}
        params.update(overrides)
        return WebhookChannel(**params)

    raise ValueError(
        f"Unsupported notification URI scheme: {uri!r}. "
        "Supported: 'email://...' or 'webhook://...'."
    )
