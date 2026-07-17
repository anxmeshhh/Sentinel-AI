"""Email delivery abstraction.

Default is ConsoleEmailSender - logs the message instead of sending it, so
signup/OTP/login flows work correctly with zero configuration. Set
EMAIL_PROVIDER=smtp and fill in SMTP_* in .env to send real emails; nothing
else in the auth flow needs to change.
"""

import smtplib
from email.mime.text import MIMEText
from typing import Protocol

import structlog

from app.core.config import get_settings

logger = structlog.get_logger("sentinel.email")


class EmailSender(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailSender:
    """Dev default. An OTP code sent this way shows up in the structured
    logs (`docker compose logs backend` or `GET /admin/logs`) instead of an
    inbox - intentional until real SMTP credentials are configured.
    """

    def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info("email_dev_console", to=to, subject=subject, body=body)


class SmtpEmailSender:
    def __init__(self, *, host: str, port: int, user: str | None, password: str | None, from_addr: str):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from = from_addr

    def send(self, *, to: str, subject: str, body: str) -> None:
        message = MIMEText(body)
        message["Subject"] = subject
        message["From"] = self._from
        message["To"] = to
        with smtplib.SMTP(self._host, self._port) as server:
            server.starttls()
            if self._user and self._password:
                server.login(self._user, self._password)
            server.sendmail(self._from, [to], message.as_string())


def get_email_sender() -> EmailSender:
    settings = get_settings()
    if settings.email_provider == "smtp" and settings.smtp_host:
        return SmtpEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            user=settings.smtp_user,
            password=settings.smtp_password,
            from_addr=settings.smtp_from,
        )
    return ConsoleEmailSender()
