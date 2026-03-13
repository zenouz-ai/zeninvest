"""SMTP email notification provider."""

import smtplib
from email.message import EmailMessage

from src.agents.notifications.providers.base import NotificationProvider
from src.agents.notifications.types import NotificationMessage


class EmailProvider(NotificationProvider):
    """Send notifications via SMTP."""

    channel = "email"

    def __init__(
        self,
        *,
        host: str | None,
        port: int,
        username: str | None,
        password: str | None,
        sender: str | None,
        recipient: str | None,
        use_tls: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.recipient = recipient
        self.use_tls = use_tls

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.port and self.sender and self.recipient)

    def send(self, message: NotificationMessage, timeout_seconds: float) -> None:
        if not self.is_configured:
            raise RuntimeError("SMTP settings not configured")
        # Narrow types for mypy: is_configured guarantees these are set
        assert self.host is not None and self.sender is not None and self.recipient is not None

        msg = EmailMessage()
        msg["Subject"] = message.subject
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg.set_content(message.body)

        with smtplib.SMTP(self.host, self.port, timeout=timeout_seconds) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password or "")
            smtp.send_message(msg)
