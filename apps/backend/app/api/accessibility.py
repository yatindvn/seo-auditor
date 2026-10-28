"""Accessibility scans (Phase 5.3). Scanning happens inside audits, so this is
read-only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.projects import _factory
from app.db.models import AccessibilityScan, Audit

router = APIRouter()


@router.get("/audits/{audit_id}/accessibility")
def audit_accessibility(audit_id: int):
    with _factory()() as session:
        audit = session.get(Audit, audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")
        rows = session.scalars(select(AccessibilityScan).where(AccessibilityScan.audit_id == audit_id)
                               .order_by(AccessibilityScan.id)).all()
        summary = audit.summary_json or {}
        return {
            "audit_id": audit_id,
            "status": summary.get("accessibility_status") or ("scanned" if rows else "disabled"),
            "reason": summary.get("accessibility_unavailable_reason"),
            "axe_version": summary.get("axe_version"),
            "items": [{
                "url": r.url, "status": r.status, "error": r.error, "score": r.score,
                "counts": {"critical": r.critical, "serious": r.serious, "moderate": r.moderate, "minor": r.minor},
                "violations": r.violations_json or [],
            } for r in rows],
        }
