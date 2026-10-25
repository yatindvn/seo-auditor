"""Send each change once per channel. The alerts row is written before the
send, so the unique (rank_check, kind, channel) constraint is what stops a
repeated run from alerting twice."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Dict, List

import requests
from sqlalchemy.exc import IntegrityError

from app.alerts.digest import format_digest
from app.db.models import Alert

logger = logging.getLogger("seo_auditor")


def deliver(factory, project_id: int, domain: str, changes: List, notifiers: List,
            now: datetime) -> Dict[str, int]:
    sent: Dict[str, int] = {}
    for notifier in notifiers:
        fresh, row_ids = [], []
        with factory.begin() as session:
            for change in changes:
                try:
                    with session.begin_nested():
                        row = Alert(project_id=project_id, keyword_id=change.keyword_id,
                                    rank_check_id=change.rank_check_id, kind=change.kind,
                                    channel=notifier.channel, sent_at=now, payload_json=asdict(change))
                        session.add(row)
                        session.flush()
                    fresh.append(change)
                    row_ids.append(row.id)
                except IntegrityError:
                    pass  # already alerted on this channel
        if not fresh:
            sent[notifier.channel] = 0
            continue
        subject, text = format_digest(domain, fresh)
        try:
            notifier.send(subject, text)
            sent[notifier.channel] = 1
        except Exception as exc:
            logger.error("Alert via %s failed: %s", notifier.channel, type(exc).__name__)
            sent[notifier.channel] = 0
            with factory.begin() as session:
                for row_id in row_ids:
                    row = session.get(Alert, row_id)
                    row.payload_json = {**row.payload_json, "error": _error_detail(exc)}
    return sent


def _error_detail(exc: Exception) -> str:
    """What to keep about a failed send. A requests error's message contains
    the URL -- for Slack, the webhook URL is the secret -- so only its type and
    status are kept."""
    if isinstance(exc, requests.RequestException):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return f"{type(exc).__name__} (status {status})"
    return f"{type(exc).__name__}: {exc}"
