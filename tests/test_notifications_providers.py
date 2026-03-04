from unittest.mock import Mock, patch

from src.agents.notifications.providers.email import EmailProvider
from src.agents.notifications.providers.slack import SlackProvider
from src.agents.notifications.types import NotificationMessage


def test_slack_provider_posts_expected_payload() -> None:
    provider = SlackProvider("https://example.test/webhook")
    message = NotificationMessage(subject="x", body="hello")

    with patch("src.agents.notifications.providers.slack.httpx.post") as post:
        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response

        provider.send(message, timeout_seconds=3)

    post.assert_called_once_with(
        "https://example.test/webhook",
        json={"text": "hello"},
        timeout=3,
    )


def test_email_provider_sends_via_smtp() -> None:
    provider = EmailProvider(
        host="localhost",
        port=1025,
        username="user",
        password="pass",
        sender="bot@example.com",
        recipient="ops@example.com",
        use_tls=True,
    )
    message = NotificationMessage(subject="Report", body="Run complete")

    with patch("src.agents.notifications.providers.email.smtplib.SMTP") as smtp_cls:
        smtp = smtp_cls.return_value.__enter__.return_value
        provider.send(message, timeout_seconds=5)

    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("user", "pass")
    smtp.send_message.assert_called_once()


def test_email_provider_without_username_skips_login() -> None:
    provider = EmailProvider(
        host="localhost",
        port=1025,
        username=None,
        password=None,
        sender="bot@example.com",
        recipient="ops@example.com",
        use_tls=False,
    )

    with patch("src.agents.notifications.providers.email.smtplib.SMTP") as smtp_cls:
        smtp = smtp_cls.return_value.__enter__.return_value
        provider.send(NotificationMessage(subject="s", body="b"), timeout_seconds=5)

    smtp.starttls.assert_not_called()
    smtp.login.assert_not_called()
