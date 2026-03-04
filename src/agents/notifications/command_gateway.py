"""Inbound command gateway scaffold for future ChatOps controls.

This scaffold is intentionally disabled in v1. Outbound notifications are the
only active chat interface feature in this release.
"""

from dataclasses import dataclass
from typing import Any

from src.utils.config import get_settings


@dataclass(slots=True)
class CommandRequest:
    """Represents an inbound chat command request."""

    source: str
    user_id: str
    channel_id: str | None
    command: str
    args: list[str]
    raw_payload: dict[str, Any]


class CommandGatewayDisabledError(RuntimeError):
    """Raised when inbound command gateway is disabled by config."""


class CommandGateway:
    """Disabled placeholder for authenticated inbound ChatOps commands."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.notification_command_gateway_enabled

    def handle(self, request: CommandRequest) -> dict[str, Any]:
        if not self.enabled:
            raise CommandGatewayDisabledError("Command gateway is disabled in configuration")

        # Placeholder only. Phase 2 will add provider signature verification,
        # allow-listing, and command audit logging.
        return {
            "status": "not_implemented",
            "command": request.command,
            "source": request.source,
        }
