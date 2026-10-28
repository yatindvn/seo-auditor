"""A project's enabled rules, as the plain dicts the engine and the page
workers use."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy import select

from app.db.engine import get_session_factory
from app.db.models import CustomRule, Project
from app.db.projects import project_domain

logger = logging.getLogger(__name__)


def rule_dict(row: CustomRule) -> Dict[str, Any]:
    return {"id": row.id, "name": row.name, "severity": row.severity, "message": row.message or "",
            "url_pattern": row.url_pattern, "check": dict(row.check_json or {})}


def load_enabled_rules(url: str, factory=None) -> List[Dict[str, Any]]:
    """The audited site's enabled rules, oldest first. Never raises: an audit
    without its custom rules beats no audit."""
    try:
        factory = factory or get_session_factory()
        with factory() as session:
            project_id = session.scalar(select(Project.id).where(Project.domain == project_domain(url)))
            if project_id is None:
                return []
            rows = session.scalars(select(CustomRule).where(
                CustomRule.project_id == project_id, CustomRule.enabled.is_(True)).order_by(CustomRule.id)).all()
            return [rule_dict(r) for r in rows]
    except Exception as exc:
        logger.error("Custom rules not loaded for %s: %s", url, exc, exc_info=exc)
        return []
