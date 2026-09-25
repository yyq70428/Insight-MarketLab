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


def app_password(raw: str) -> str:
    """Google prints app passwords as 'abcd efgh ijkl mnop'; the spaces are presentation only."""
    return "".join(raw.split())


def missing_settings() -> list[str]:
    """Everything wrong with the mail config, in words the operator can act on."""
    settings = get_settings()
    problems = []
    if not settings.smtp_host:
        problems.append("SMTP_HOST 未設定")
    if not settings.sender_address:
        problems.append("SMTP_FROM 或 SMTP_USER 未設定")
    if not settings.recipient_list:
        problems.append("REPORT_RECIPIENTS 未設定")
    # SMTP AUTH is ASCII-only. Pasting a placeholder or a Chinese note as the value otherwise
    # surfaces as UnicodeEncodeError from deep inside smtplib, which says nothing useful.
    for label, value in (("SMTP_USER", settings.smtp_user), ("SMTP_PASSWORD", app_password(settings.smtp_password))):
        if value and not value.isascii():
            problems.append(f"{label} 含中文或其他非 ASCII 字元，看起來是把說明文字當成值貼上了")
    for label, value in (("SMTP_FROM", settings.smtp_from), ("SMTP_USER", settings.smtp_user)):
        if value and ("@" not in value or value.startswith("<")):
            problems.append(f"{label} 不是一個電子郵件位址")
    return problems


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
    problems = missing_settings()
    if problems:
        raise MailNotConfigured("郵件設定有問題：" + "；".join(problems))
    targets = recipients or settings.recipient_list
    message = build_message(subject, html, text, targets)
    context = ssl.create_default_context()
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout, context=context) as server:
            if settings.smtp_user:
                server.login(settings.smtp_user, app_password(settings.smtp_password))
            server.send_message(message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout) as server:
            server.ehlo()
            if settings.smtp_starttls:
                server.starttls(context=context)
                server.ehlo()
            if settings.smtp_user:
                server.login(settings.smtp_user, app_password(settings.smtp_password))
            server.send_message(message)
    return {"sent": True, "recipients": targets, "subject": subject}
