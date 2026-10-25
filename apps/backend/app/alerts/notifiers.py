"""Alert channels. Each is configured only when its settings are present."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import List

import requests

from app.config import config


class SlackNotifier:
    channel = "slack"

    def __init__(self, webhook_url: str) -> None:
        self._url = webhook_url

    def send(self, subject: str, text: str) -> None:
        requests.post(self._url, json={"text": f"*{subject}*\n{text}"}, timeout=10).raise_for_status()


class EmailNotifier:
    channel = "email"

    def __init__(self, host, port, user, password, sender, recipients: List[str]) -> None:
        self._host, self._port = host, port
        self._user, self._password = user, password
        self._sender, self._recipients = sender, recipients

    def send(self, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, self._sender, ", ".join(self._recipients)
        msg.set_content(text)
        with smtplib.SMTP(self._host, self._port, timeout=20) as smtp:
            smtp.starttls()
            if self._user:
                smtp.login(self._user, self._password)
            smtp.send_message(msg)


def configured_notifiers(cfg=config) -> list:
    found = []
    if cfg.SLACK_WEBHOOK_URL:
        found.append(SlackNotifier(cfg.SLACK_WEBHOOK_URL))
    if cfg.SMTP_HOST and cfg.ALERT_EMAIL_FROM and cfg.ALERT_EMAIL_TO:
        found.append(EmailNotifier(cfg.SMTP_HOST, cfg.SMTP_PORT, cfg.SMTP_USER,
                                   cfg.SMTP_PASSWORD, cfg.ALERT_EMAIL_FROM, cfg.ALERT_EMAIL_TO))
    return found
