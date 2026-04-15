"""Notification channels for pipeline events."""

from dagloom.notifications.base import ExecutionEvent, NotificationChannel
from dagloom.notifications.email import SMTPChannel
from dagloom.notifications.registry import ChannelRegistry, resolve_channel
from dagloom.notifications.webhook import WebhookChannel

__all__ = [
    "ChannelRegistry",
    "ExecutionEvent",
    "NotificationChannel",
    "SMTPChannel",
    "WebhookChannel",
    "resolve_channel",
]
