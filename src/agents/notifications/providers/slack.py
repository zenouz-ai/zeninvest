"""Slack webhook notification provider."""

import httpx

from src.agents.notifications.providers.base import NotificationProvider
from src.agents.notifications.types import NotificationMessage


class SlackProvider(NotificationProvider):
    """Send notifications to Slack via incoming webhook."""

    channel = "slack"

    def __init__(self, webhook_url: str | None) -> None:
        self.webhook_url = webhook_url
        self.recipient = webhook_url

    @property
    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    def send(self, message: NotificationMessage, timeout_seconds: float) -> None:
        if not self.webhook_url:
            raise RuntimeError("Slack webhook URL not configured")

        response = httpx.post(
            self.webhook_url,
            json={"text": message.body},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
