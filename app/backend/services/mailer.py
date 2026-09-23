"""SMTP delivery for scheduled reports.

Standard library only, so no new dependency enters the image. Port 465 is treated as
implicit TLS and everything else upgrades with STARTTLS, which covers Gmail (587) and
the usual managed relays without a per-provider branch.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from ..config import get_settings


class MailNotConfigured(RuntimeError):
    pass


def missing_settings() -> list[str]:
    settings = get_settings()
    missing = []
    if not settings.smtp_host:
        missing.append("SMTP_HOST")
    if not settings.sender_address:
        missing.append("SMTP_FROM 或 SMTP_USER")
    if not settings.recipient_list:
        missing.append("REPORT_RECIPIENTS")
    return missing


def mail_configured() -> bool:
    return not missing_settings()


def build_message(subject: str, html: str, text: str, recipients: list[str], sender_name: str = "MarketLab") -> EmailMessage:
    settings = get_settings()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((sender_name, settings.sender_address))
    message["To"] = ", ".join(recipients)
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=settings.sender_address.split("@")[-1] or "marketlab.local")
    # Plain text first, so clients that refuse HTML still get a readable report.
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def send_mail(subject: str, html: str, text: str, recipients: list[str] | None = None) -> dict:
    settings = get_settings()
    missing = missing_settings()
    if missing:
        raise MailNotConfigured("郵件設定不完整，缺少：" + "、".join(missing))
    targets = recipients or settings.recipient_list
    message = build_message(subject, html, text, targets)
    context = ssl.create_default_context()
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout, context=context) as server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout) as server:
            server.ehlo()
            if settings.smtp_starttls:
                server.starttls(context=context)
                server.ehlo()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    return {"sent": True, "recipients": targets, "subject": subject}
