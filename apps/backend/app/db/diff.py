"""Diff two audits of one project in SQL -- anti-joins on indexed columns --
rather than loading 5000-page audits into Python."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.db.models import Audit, AuditIssue, AuditPage


def _issues_only_in(session: Session, keep_id: int, other_id: int, limit: int):
    other = aliased(AuditIssue)
    missing = ~exists().where(and_(
        other.audit_id == other_id, other.url == AuditIssue.url, other.code == AuditIssue.code,
    ))
    where = and_(AuditIssue.audit_id == keep_id, missing)
    count = session.scalar(
        select(func.count()).select_from(
            select(AuditIssue.url, AuditIssue.code).where(where).distinct().subquery()
        )
    )
    rows = session.execute(
        select(AuditIssue.url, AuditIssue.code, func.min(AuditIssue.severity), func.min(AuditIssue.message))
        .where(where).group_by(AuditIssue.url, AuditIssue.code)
        .order_by(AuditIssue.url, AuditIssue.code).limit(limit)
    ).all()
    items = [{"url": u, "code": c, "severity": s, "message": m} for u, c, s, m in rows]
    return items, count


def _persisting(session: Session, old_id: int, new_id: int) -> int:
    other = aliased(AuditIssue)
    present = exists().where(and_(
        other.audit_id == old_id, other.url == AuditIssue.url, other.code == AuditIssue.code,
    ))
    return session.scalar(
        select(func.count()).select_from(
            select(AuditIssue.url, AuditIssue.code)
            .where(AuditIssue.audit_id == new_id, present).distinct().subquery()
        )
    )


def _pages_only_in(session: Session, keep_id: int, other_id: int, limit: int):
    other = aliased(AuditPage)
    where = and_(AuditPage.audit_id == keep_id, ~exists().where(and_(
        other.audit_id == other_id, other.url == AuditPage.url,
    )))
    count = session.scalar(select(func.count()).select_from(AuditPage).where(where))
    urls = session.scalars(select(AuditPage.url).where(where).order_by(AuditPage.url).limit(limit)).all()
    return list(urls), count


def _status_changed(session: Session, old_id: int, new_id: int, limit: int):
    old, new = aliased(AuditPage), aliased(AuditPage)
    where = and_(old.audit_id == old_id, new.audit_id == new_id, old.url == new.url,
                 old.status.is_distinct_from(new.status))
    joined = select(old.url, old.status, new.status).join(new, old.url == new.url).where(where)
    count = session.scalar(select(func.count()).select_from(joined.subquery()))
    rows = session.execute(joined.order_by(old.url).limit(limit)).all()
    return [{"url": u, "old_status": o, "new_status": n} for u, o, n in rows], count


def diff_audits(session: Session, old_id: int, new_id: int, limit: int = 500) -> Dict[str, Any]:
    old, new = session.get(Audit, old_id), session.get(Audit, new_id)
    if old is None or new is None:
        raise LookupError(f"no audit {old_id if old is None else new_id}")
    if old.project_id != new.project_id:
        raise ValueError("audits belong to different projects")

    new_issues, new_count = _issues_only_in(session, new_id, old_id, limit)
    fixed, fixed_count = _issues_only_in(session, old_id, new_id, limit)
    added, added_count = _pages_only_in(session, new_id, old_id, limit)
    removed, removed_count = _pages_only_in(session, old_id, new_id, limit)
    changed, changed_count = _status_changed(session, old_id, new_id, limit)

    score_change = None
    if old.health_score is not None and new.health_score is not None:
        score_change = round(new.health_score - old.health_score, 2)

    return {
        "old_audit_id": old_id, "new_audit_id": new_id,
        "health_score_change": score_change,
        "issues": {"new": new_issues, "fixed": fixed, "new_count": new_count,
                   "fixed_count": fixed_count, "persisting_count": _persisting(session, old_id, new_id)},
        "pages": {"added": added, "removed": removed, "status_changed": changed,
                  "added_count": added_count, "removed_count": removed_count,
                  "status_changed_count": changed_count},
    }


def previous_audit_id(session: Session, audit_id: int) -> Optional[int]:
    audit = session.get(Audit, audit_id)
    if audit is None:
        return None
    return session.scalar(
        select(Audit.id).where(
            Audit.project_id == audit.project_id,
            (Audit.finished_at < audit.finished_at)
            | (and_(Audit.finished_at == audit.finished_at, Audit.id < audit.id)),
        ).order_by(Audit.finished_at.desc(), Audit.id.desc()).limit(1)
    )
