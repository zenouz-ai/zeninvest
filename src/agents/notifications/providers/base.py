"""Base class for outbound notification providers."""

from abc import ABC, abstractmethod

from src.agents.notifications.types import NotificationMessage


class NotificationProvider(ABC):
    """Provider contract for outbound notification channels."""

    channel: str
    recipient: str | None

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Whether provider has sufficient config to send notifications."""

    @abstractmethod
    def send(self, message: NotificationMessage, timeout_seconds: float) -> None:
        """Send the rendered message or raise on failure."""
