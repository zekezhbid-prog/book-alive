"""Sending the password reset mail through an SMTP account (Gmail with an app password)."""

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger(__name__)


def configured() -> bool:
    return bool(settings.smtp_user and settings.smtp_password)


def send(to: str, subject: str, body: str) -> None:
    """Fire-and-forget: a mail problem is logged, never shown to whoever asked for the reset
    (that would reveal which addresses have accounts)."""
    if not configured():
        log.warning("SMTP is not configured: the mail to %s was not sent", to)
        return
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        log.exception("could not send the mail to %s", to)
