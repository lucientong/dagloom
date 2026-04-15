"""SMTP email notification channel.

Sends pipeline execution results via email using ``aiosmtplib``
for fully async delivery.

Example::

    channel = SMTPChannel(
        host="smtp.gmail.com",
        port=587,
        username="user@gmail.com",
        password="app-password",
        use_tls=True,
        from_addr="user@gmail.com",
        to_addrs=["ops@team.com"],
    )
    await channel.send(event)
"""

from __future__ import annotations

import logging
from email.message import EmailMessage

from dagloom.notifications.base import ExecutionEvent, NotificationChannel

logger = logging.getLogger(__name__)


class SMTPChannel(NotificationChannel):
    """Email notification channel via SMTP.

    Args:
        host: SMTP server hostname.
        port: SMTP server port (587 for STARTTLS, 465 for SSL).
        username: SMTP login username (optional for unauthenticated relays).
        password: SMTP login password.
        use_tls: Whether to use STARTTLS (default True).
        from_addr: Sender email address.
        to_addrs: List of recipient email addresses.
        subject_template: Subject line template — ``{status}`` and
            ``{pipeline_name}`` are replaced at send time.
    """

    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        from_addr: str = "dagloom@localhost",
        to_addrs: list[str] | None = None,
        subject_template: str = "[Dagloom] {pipeline_name} — {status}",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_addr = from_addr
        self.to_addrs = to_addrs or []
        self.subject_template = subject_template

    async def send(self, event: ExecutionEvent) -> None:
        """Send an email notification.

        Args:
            event: The execution event to report.

        Raises:
            ImportError: If ``aiosmtplib`` is not installed.
            Exception: If SMTP delivery fails.
        """
        try:
            import aiosmtplib
        except ImportError as exc:
            raise ImportError(
                "aiosmtplib is required for email notifications. "
                "Install it with: pip install aiosmtplib"
            ) from exc

        if not self.to_addrs:
            logger.warning("SMTPChannel: no recipients configured, skipping.")
            return

        msg = self._build_message(event)

        await aiosmtplib.send(
            msg,
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            start_tls=self.use_tls,
        )
        logger.info(
            "Email sent to %s for pipeline '%s' (%s).",
            ", ".join(self.to_addrs),
            event.pipeline_name,
            event.status,
        )

    def _build_message(self, event: ExecutionEvent) -> EmailMessage:
        """Build an ``EmailMessage`` from the execution event."""
        msg = EmailMessage()
        msg["Subject"] = self.subject_template.format(
            pipeline_name=event.pipeline_name,
            status=event.status.upper(),
        )
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)

        body = self._format_body(event)
        msg.set_content(body)
        return msg

    @staticmethod
    def _format_body(event: ExecutionEvent) -> str:
        """Format the email body as plain text."""
        lines = [
            f"Pipeline: {event.pipeline_name}",
            f"Status: {event.status.upper()}",
            f"Execution ID: {event.execution_id}",
            f"Started: {event.started_at}",
            f"Finished: {event.finished_at}",
            f"Duration: {event.duration_seconds:.1f}s",
            f"Nodes: {event.node_count}",
        ]
        if event.error_message:
            lines.append(f"\nError: {event.error_message}")
        if event.failed_node:
            lines.append(f"Failed Node: {event.failed_node}")
        lines.append("\n--\nSent by Dagloom")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"SMTPChannel(host={self.host!r}, to={self.to_addrs!r})"
