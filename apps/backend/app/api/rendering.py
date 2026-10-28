"""Raw-vs-rendered comparisons (Phase 5.2). Rendering happens inside audits,
so this is read-only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.projects import _factory
from app.db.models import Audit, RenderedPage

router = APIRouter()


@router.get("/audits/{audit_id}/rendering")
def audit_rendering(audit_id: int):
    with _factory()() as session:
        audit = session.get(Audit, audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")
        rows = session.scalars(select(RenderedPage).where(RenderedPage.audit_id == audit_id)
                               .order_by(RenderedPage.id)).all()
        summary = audit.summary_json or {}
        return {
            "audit_id": audit_id,
            "status": summary.get("render_status") or ("rendered" if rows else "disabled"),
            "reason": summary.get("render_unavailable_reason"),
            "items": [{
                "url": r.url, "status": r.status, "error": r.error, "render_ms": r.render_ms,
                "raw_word_count": r.raw_word_count, "rendered_word_count": r.rendered_word_count,
                "changes": r.changes_json or {}, "js_only_links": r.js_only_links_json or [],
                "js_only_links_count": r.js_only_links_count,
            } for r in rows],
        }
