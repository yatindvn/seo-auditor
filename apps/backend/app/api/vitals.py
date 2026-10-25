"""Core Web Vitals read endpoints (Phase 5.1). Measuring happens inside
audits, so there is nothing to write here."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.projects import _factory
from app.db.models import Audit, Project, WebVital, as_utc
from app.vitals.model import metric_ratings

router = APIRouter()

_FIELDS = ("url", "strategy", "source", "data_kind", "rating", "performance_score",
           "lcp_ms", "inp_ms", "cls", "fcp_ms", "ttfb_ms", "tbt_ms", "error")


def _row_json(v: WebVital) -> Dict[str, Any]:
    return {**{f: getattr(v, f) for f in _FIELDS},
            "measured_at": as_utc(v.measured_at).isoformat() if v.measured_at else None,
            "metric_ratings": metric_ratings(v)}


@router.get("/audits/{audit_id}/vitals")
def audit_vitals(audit_id: int):
    with _factory()() as session:
        audit = session.get(Audit, audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")
        rows = session.scalars(select(WebVital).where(WebVital.audit_id == audit_id).order_by(WebVital.id)).all()
        status = (audit.summary_json or {}).get("web_vitals_status") or ("measured" if rows else "not_configured")
        return {"audit_id": audit_id, "status": status, "items": [_row_json(v) for v in rows]}


@router.get("/projects/{project_id}/vitals/trend")
def vitals_trend(project_id: int, limit: int = Query(30, ge=1, le=200)):
    """The homepage per audit, oldest first. The homepage is each audit's
    first measured row, because pages are measured start URL first. Audits
    whose homepage wasn't measured are skipped."""
    with _factory()() as session:
        if session.get(Project, project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        audits = session.scalars(
            select(Audit).where(Audit.project_id == project_id)
            .order_by(Audit.finished_at.desc(), Audit.id.desc()).limit(limit)
        ).all()
        points = []
        for audit in reversed(audits):
            home = session.scalar(select(WebVital).where(WebVital.audit_id == audit.id)
                                  .order_by(WebVital.id).limit(1))
            if home is None or home.error:
                continue
            points.append({
                "audit_id": audit.id, "finished_at": as_utc(audit.finished_at).isoformat(),
                "url": home.url, "source": home.source, "data_kind": home.data_kind,
                "performance_score": home.performance_score, "lcp_ms": home.lcp_ms,
                "inp_ms": home.inp_ms, "cls": home.cls, "tbt_ms": home.tbt_ms,
                "rating": home.rating, "metric_ratings": metric_ratings(home),
            })
        return {"url": points[-1]["url"] if points else None, "points": points}
